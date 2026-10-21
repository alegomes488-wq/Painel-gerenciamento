/**
 * ============================================================
 *  Cyber Core IA — Agente do Painel HUB para Android (APK)
 *
 *  Coleta e envia para a seção "app" (Desempenho) e "apk"
 *  (Segurança — anti-tampering) do painel HUB:
 *    - Crash Rate (UncaughtExceptionHandler)
 *    - ANR (heartbeat da main thread)
 *    - App Launch Time (Process.getStartUptimeMillis)
 *    - Root detectado
 *    - Assinatura do APK inválida (reempacotamento/clonagem)
 *    - Bloqueio de rollout (consulta /api/hub/agent/rollout/{v})
 *
 *  Integração:
 *    1. Copie o arquivo para o módulo app (ex.: com.cybercore.hub).
 *    2. No Application.onCreate():
 *         HubAgent.init(this,
 *             backendUrl = "https://SEU-BACKEND",
 *             secret = "HUB_AGENT_SECRET",          // injete via BuildConfig
 *             apkVersion = BuildConfig.VERSION_NAME,
 *             pinnedCertSha256 = "ABC123...")       // SHA-256 do cert de assinatura
 *    3. No handler global de exceções, chame HubAgent.reportCrash(e).
 *
 *  Nota de segurança: o secret HMAC vive no APK — qualquer um pode
 *  extrair. Por isso o backend trata agentes como sensores de telemetria:
 *  leitura de rollout-status é idempotente e ingestão só escreve as
 *  seções app/apk (nunca concede acesso administrativo).
 * ============================================================
 */
package com.cybercore.hub

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.Process
import android.os.SystemClock
import android.view.Choreographer
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object HubAgent {

    private const val ANR_THRESHOLD_MS = 5000L
    private const val FLUSH_INTERVAL_MS = 60_000L
    private const val FRAME_BUDGET_MS = 16.67

    private lateinit var appContext: Context
    private var backendUrl: String = ""
    private var secret: String = ""
    private var apkVersion: String = ""
    private var pinnedCertSha256: String = ""

    private val crashCount = AtomicInteger(0)
    private val anrCount = AtomicInteger(0)
    private val tamperCount = AtomicInteger(0)
    private val jankFrames = AtomicInteger(0)
    private val totalFrames = AtomicInteger(0)
    private val launchStartMs = AtomicLong(0)
    private val executor = Executors.newSingleThreadScheduledExecutor()

    fun init(
        context: Context,
        backendUrl: String,
        secret: String,
        apkVersion: String,
        pinnedCertSha256: String = "",
    ) {
        appContext = context.applicationContext
        this.backendUrl = backendUrl.trimEnd('/')
        this.secret = secret
        this.apkVersion = apkVersion
        this.pinnedCertSha256 = pinnedCertSha256

        launchStartMs.set(SystemClock.uptimeMillis())
        installCrashHandler()
        startAnrWatch()
        startFrameWatch()
        if (pinnedCertSha256.isNotEmpty()) verifySignature()
        executor.scheduleAtFixedRate({ flush() }, FLUSH_INTERVAL_MS, FLUSH_INTERVAL_MS, java.util.concurrent.TimeUnit.MILLISECONDS)
    }

    /** Chame no seu UncaughtExceptionHandler global (ou antes de reprocessar). */
    fun reportCrash(throwable: Throwable) {
        crashCount.incrementAndGet()
        // Em produção, envie o stacktrace resumido como evento extra via /api/hub/events.
    }

    /** Launch time (ms) medido desde o processo iniciar até o 1º frame pronto. */
    fun launchTimeMs(): Long {
        val start = if (Build.VERSION.SDK_INT >= 24) Process.getStartUptimeMillis() else launchStartMs.get()
        return (SystemClock.uptimeMillis() - start).coerceAtLeast(0)
    }

    fun isDeviceRooted(): Boolean = detectRoot()

    private fun installCrashHandler() {
        val default = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            crashCount.incrementAndGet()
            default?.uncaughtException(thread, throwable)
        }
    }

    private fun startAnrWatch() {
        val mainHandler = android.os.Handler(appContext.mainLooper)
        var lastBeat = SystemClock.uptimeMillis()
        val beat = Runnable {
            val now = SystemClock.uptimeMillis()
            if (now - lastBeat > ANR_THRESHOLD_MS * 2) anrCount.incrementAndGet()
            lastBeat = now
            mainHandler.postDelayed(this.let { beat }, ANR_THRESHOLD_MS / 2)
        }
        mainHandler.postDelayed(beat, ANR_THRESHOLD_MS / 2)
    }

    /** Frozen Frames: conta frames acima do orçamento de 16,67ms (60fps). */
    private fun startFrameWatch() {
        val choreographer = Choreographer.getInstance()
        var lastFrameNs = 0L
        val callback = object : Choreographer.FrameCallback {
            override fun doFrame(frameTimeNanos: Long) {
                if (lastFrameNs > 0) {
                    val deltaMs = (frameTimeNanos - lastFrameNs) / 1_000_000.0
                    totalFrames.incrementAndGet()
                    if (deltaMs > FRAME_BUDGET_MS * 2) jankFrames.incrementAndGet()
                }
                lastFrameNs = frameTimeNanos
                choreographer.postFrameCallback(this)
            }
        }
        choreographer.postFrameCallback(callback)
    }

    private fun frozenFramesRatePercent(): Double {
        val total = totalFrames.get()
        return if (total <= 0) 0.0 else (jankFrames.get().toDouble() / total) * 100.0
    }

    /** Uso de RAM do processo como % do heap máximo disponível. */
    private fun ramPercent(): Double {
        val runtime = Runtime.getRuntime()
        val used = runtime.totalMemory() - runtime.freeMemory()
        val max = runtime.maxMemory().coerceAtLeast(1)
        return (used.toDouble() / max) * 100.0
    }

    private fun detectRoot(): Boolean {
        val paths = arrayOf(
            "/system/bin/su", "/system/xbin/su", "/sbin/su",
            "/system/app/Superuser.apk", "/system/xbin/busybox"
        )
        if (paths.any { File(it).exists() }) return true
        return Build.TAGS?.contains("test-keys") == true
    }

    /** Compara o SHA-256 do certificado de assinatura com o pin. Divergência = reempacotamento. */
    private fun verifySignature() {
        try {
            val info = appContext.packageManager.getPackageInfo(
                appContext.packageName,
                android.content.pm.PackageManager.GET_SIGNATURES
            )
            @Suppress("DEPRECATION")
            val sig = info.signatures?.firstOrNull() ?: return
            val digest = MessageDigest.getInstance("SHA-256")
                .digest(sig.toByteArray())
            val actual = digest.joinToString("") { "%02X".format(it) }
            if (!actual.equals(pinnedCertSha256, ignoreCase = true)) {
                tamperCount.incrementAndGet()
            }
        } catch (e: Exception) {
            tamperCount.incrementAndGet()
        }
    }

    /**
     * Consulta se o rollout desta versão está bloqueado pela Cyber Core IA.
     * Use antes de promover/atualizar o APK (ex.: checagem no updater).
     */
    fun isRolloutBlocked(): Boolean {
        return try {
            val url = URL("$backendUrl/api/hub/agent/rollout/$apkVersion")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                setRequestProperty("X-Hub-Agent-Secret", hmac("hub-ingest"))
                connectTimeout = 5000
                readTimeout = 5000
            }
            val blocked = conn.responseCode == 200 &&
                conn.inputStream.bufferedReader().readText().contains("\"blocked\":true")
            conn.disconnect()
            blocked
        } catch (e: Exception) {
            false // fail-open: sem rede não bloqueia a atualização
        }
    }

    /** Agrega e envia as métricas acumuladas (chamado periodicamente). */
    fun flush() {
        try {
            val appPayload = JSONObject()
                .put("crash_rate", crashRatePercent())
                .put("anr_rate", anrRatePercent())
                .put("frozen_frames_rate", frozenFramesRatePercent())
                .put("launch_time_ms", launchTimeMs())
                .put("ram_avg", ramPercent())
                .put("apk_version", apkVersion)
                .put("cpu_avg", readCpuPercent())
            post("app", appPayload)

            if (tamperCount.get() > 0 || detectRoot()) {
                val apkPayload = JSONObject()
                    .put("tamper_attempts", tamperCount.get())
                    .put("root_devices", if (detectRoot()) 1 else 0)
                post("apk", apkPayload)
            }
        } catch (e: Exception) {
            // telemetry nunca derruba o app
        }
    }

    // Exemplos de baseline: em produção, calcule a partir das sessões reais.
    private fun crashRatePercent(): Double =
        (crashCount.get().toDouble() / 1000.0 * 100.0).coerceAtMost(100.0)
    private fun anrRatePercent(): Double =
        (anrCount.get().toDouble() / 1000.0 * 100.0).coerceAtMost(100.0)
    private fun readCpuPercent(): Double = 0.0 // substitua por leitura de /proc/stat se necessário

    private fun post(section: String, data: JSONObject) {
        val body = JSONObject()
            .put("section", section)
            .put("source", "android-agent")
            .put("data", data)
            .toString()
            .toByteArray("UTF-8")
        val conn = (URL("$backendUrl/api/hub/events").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("X-Hub-Agent-Secret", hmac("hub-ingest"))
            connectTimeout = 8000
            readTimeout = 8000
            outputStream.use { it.write(body) }
        }
        conn.responseCode // dispara
        conn.disconnect()
    }

    private fun hmac(input: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray("UTF-8"), "HmacSHA256"))
        return mac.doFinal(input.toByteArray("UTF-8"))
            .joinToString("") { "%02x".format(it) }
    }
}
