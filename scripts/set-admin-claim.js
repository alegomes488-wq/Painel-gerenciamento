#!/usr/bin/env node
/**
 * set-admin-claim.js — Fallback CLI para conceder/revogar o custom claim de admin.
 *
 * PROBLEMA (auditoria F-BE-01 / F-AUTH-02):
 *  O painel depende do endpoint /api/auth/refresh-admin-claim para propagar o claim
 *  de admin. Se esse endpoint falhar ou for removido, NÃO existe recovery path para
 *  promover um administrador. Este script é a porta de emergência.
 *
 * USO:
 *   node scripts/set-admin-claim.js <UID> [--revoke]
 *
 *   Ex.: node scripts/set-admin-claim.js AbCdEf123456 --revoke
 *
 * REQUISITOS:
 *   - Credencial de Service Account (firebase-adminsdk.json) ou env var
 *     FIREBASE_SERVICE_ACCOUNT / GOOGLE_APPLICATION_CREDENTIALS.
 *   - `firebase-admin` instalado (rode `npm install firebase-admin` em scripts/ se faltar).
 *
 * SEGURANÇA:
 *   NUNCA versionar este script com credenciais. A chave vem do ambiente/arquivo
 *   fora do git (gitignored). Após conceder o claim, os refresh tokens são revogados
 *   para forçar novo login e propagação imediata do claim.
 */

// ── Carrega Variáveis do .env (raiz do projeto) sem depender de dotenv ──
function loadDotEnv() {
  const fs = require('fs');
  const path = require('path');
  const envPath = path.join(__dirname, '..', '.env');
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf-8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let val = trimmed.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = val;
  }
}
loadDotEnv();

const admin = require('firebase-admin');
let auth = null; // resolvido após initAdmin()

// ── Bootstrap do Admin SDK ──
// firebase-admin v14: cert fica em firebase-admin/app (não em admin.credential)
let appCert = null;
try {
  appCert = require('firebase-admin/app').cert;
} catch (e) {
  appCert = admin.credential.cert;
}

function initAdmin() {
  // 1. Env var com conteudo do service account (recomendado)
  const saJson = process.env.FIREBASE_SERVICE_ACCOUNT;
  if (saJson) {
    return admin.initializeApp({ credential: appCert(JSON.parse(saJson)) });
  }
  // 2. Arquivo local (gitignored)
  const fs = require('fs');
  const path = require('path');
  const defaultPath = path.join(__dirname, '..', 'firebase-adminsdk.json');
  const candidate = process.env.FIREBASE_ADMIN_JSON_PATH || defaultPath;
  if (fs.existsSync(candidate)) {
    return admin.initializeApp({ credential: appCert(candidate) });
  }
  // 3. Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS)
  return admin.initializeApp();
}

function usage() {
  console.log('Uso: node scripts/set-admin-claim.js <UID> [--revoke]');
  console.log('  --revoke  remove o claim de admin (em vez de conceder)');
  process.exit(1);
}

async function main() {
  const args = process.argv.slice(2);
  const uid = args[0];
  const revoke = args.includes('--revoke');

  if (!uid) usage();

  initAdmin();

  // Resolve o AuthService DEPOIS da inicialização (getAuth exige app pronto)
  auth = require('firebase-admin/auth').getAuth();

  try {
    const claims = { admin: !revoke };
    await auth.setCustomUserClaims(uid, claims);
    console.log(`[set-admin-claim] ${revoke ? 'Removido' : 'Concedido'} claim { admin: ${!revoke} } para UID ${uid}`);

    // Revoga refresh tokens para forçar novo login e propagar o claim imediatamente
    await auth.revokeRefreshTokens(uid);
    console.log(`[set-admin-claim] Refresh tokens revogados para ${uid} (novo login necessário).`);

    console.log('[set-admin-claim] OK');
  } catch (err) {
    console.error('[set-admin-claim] ERRO:', err.message);
    process.exit(1);
  }
}

main();
