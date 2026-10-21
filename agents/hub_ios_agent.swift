import Foundation
import UIKit

/// ============================================================
///  Cyber Core IA — Agente do Painel HUB para iOS (PWA/iOS)
///
///  Coleta e envia para a seção "app" (Desempenho) e "apk"
///  (Segurança — jailbreak) do painel HUB:
///    - Crash Rate (sinal SIGABRT/SIGSEGV + NSSetUncaughtExceptionHandler)
///    - App Launch Time (processInfo.systemUptime no primeiro frame)
///    - Jailbreak detectado
///
///  Integração (no AppDelegate):
///    HubAgent.shared.start(
///        backendURL: URL(string: "https://SEU-BACKEND")!,
///        secret: "HUB_AGENT_SECRET",   // injete via build setting/xcconfig
///        appVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
///    )
///
///  Nota: o secret vive no binário — trate o agente como sensor de
///  telemetria (o backend só aceita seções app/apk dele).
/// ============================================================

final class HubAgent {
    static let shared = HubAgent()

    private var backendURL: URL?
    private var secret = ""
    private var appVersion = ""
    private var crashCount = 0
    private var launchStart = ProcessInfo.processInfo.systemUptime
    private var timer: Timer?

    func start(backendURL: URL, secret: String, appVersion: String, flushInterval: TimeInterval = 60) {
        self.backendURL = backendURL
        self.secret = secret
        self.appVersion = appVersion
        self.launchStart = ProcessInfo.processInfo.systemUptime
        installCrashHandlers()
        timer = Timer.scheduledTimer(withTimeInterval: flushInterval, repeats: true) { [weak self] _ in
            self?.flush()
        }
    }

    /// Chame no seu handler de exceções (ou no relatório de crash).
    func reportCrash(_ exception: NSException) {
        crashCount += 1
    }

    private func installCrashHandlers() {
        NSSetUncaughtExceptionHandler { exception in
            HubAgent.shared.reportCrash(exception)
        }
        signal(SIGABRT) { _ in HubAgent.shared.handleFatalSignal() }
        signal(SIGSEGV) { _ in HubAgent.shared.handleFatalSignal() }
        signal(SIGILL)  { _ in HubAgent.shared.handleFatalSignal() }
    }

    fileprivate static func handleFatalSignal() {
        shared.crashCount += 1
        // Em produção, re-registre o handler default antes de encerrar.
    }

    private var launchTimeMs: Int {
        Int((ProcessInfo.processInfo.systemUptime - launchStart) * 1000)
    }

    static func isJailbroken() -> Bool {
        let suspiciousPaths = [
            "/Applications/Cydia.app",
            "/Library/MobileSubstrate/MobileSubstrate.dylib",
            "/bin/bash", "/usr/sbin/sshd", "/etc/apt",
        ]
        if suspiciousPaths.contains(where: { FileManager.default.fileExists(atPath: $0) }) { return true }
        if !FileManager.default.isExecutableFile(atPath: "/bin/sh") { return true }
        return false
    }

    func flush() {
        guard let backendURL = backendURL else { return }
        var appData: [String: Any] = [
            "crash_rate": Double(crashCount) / 1000.0 * 100.0,
            "launch_time_ms": launchTimeMs,
            "apk_version": appVersion,
        ]
        post(section: "app", data: appData)

        if Self.isJailbroken() {
            post(section: "apk", data: ["jailbreak_devices": 1])
        }
    }

    private func post(section: String, data: [String: Any]) {
        guard let endpoint = URL(string: "/api/hub/events", relativeTo: backendURL) else { return }
        var request = URLRequest(url: endpoint, timeoutInterval: 8)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(hmacHex("hub-ingest"), forHTTPHeaderField: "X-Hub-Agent-Secret")
        let payload: [String: Any] = ["section": section, "source": "ios-agent", "data": data]
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        URLSession.shared.dataTask(with: request).resume() // fire-and-forget
    }

    private func hmacHex(_ input: String) -> String {
        // Substitua pelo HMAC-SHA256 da sua stack (ex.: CryptoKit).
        // Exemplo com CommonCrypto:
        //   HMAC<SHA256>.authenticationCode(for: Data(input.utf8), using: SymmetricKey(data: Data(secret.utf8)))
        var digest = [UInt8](repeating: 0, count: 32)
        CCHmac(CCHmacAlgorithm(kCCHmacAlgSHA256), secret, secret.count, input, input.count, &digest)
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
