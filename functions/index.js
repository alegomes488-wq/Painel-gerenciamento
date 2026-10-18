const functions = require('firebase-functions');
const admin = require('firebase-admin');

admin.initializeApp();

const ALLOWED_AMOUNTS_DEFAULT = [0.5, 3.0, 5.0, 10.0, 50.0];
const VALID_PIX_TYPES = ['CPF', 'CNPJ', 'EMAIL', 'PHONE', 'EVP'];

function validatePixKey(type, key) {
  if (!key) return 'Chave PIX obrigatória.';
  if (type === 'CPF') {
    const cpf = key.replace(/\D/g, '');
    if (cpf.length !== 11 || /^(\d)\1+$/.test(cpf)) return 'CPF inválido.';
    for (let j = 9; j <= 10; j++) {
      let s = 0;
      for (let i = 0; i < j; i++) s += parseInt(cpf[i]) * (j + 1 - i);
      let d = (s * 10) % 11;
      if (d === 10) d = 0;
      if (d !== parseInt(cpf[j])) return 'CPF inválido.';
    }
    return null;
  }
  if (type === 'CNPJ') {
    const cnpj = key.replace(/\D/g, '');
    if (cnpj.length !== 14 || /^(\d)\1+$/.test(cnpj)) return 'CNPJ inválido.';
    const weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    let s1 = 0;
    for (let i = 0; i < 12; i++) s1 += parseInt(cnpj[i]) * weights1[i];
    let d1 = 11 - (s1 % 11);
    if (d1 >= 10) d1 = 0;
    if (d1 !== parseInt(cnpj[12])) return 'CNPJ inválido.';
    const weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
    let s2 = 0;
    for (let i = 0; i < 13; i++) s2 += parseInt(cnpj[i]) * weights2[i];
    let d2 = 11 - (s2 % 11);
    if (d2 >= 10) d2 = 0;
    if (d2 !== parseInt(cnpj[13])) return 'CNPJ inválido.';
    return null;
  }
  if (type === 'EMAIL') {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(key) ? null : 'E-mail inválido.';
  }
  if (type === 'PHONE') {
    const p = key.replace(/\D/g, '');
    return (p.length >= 10 && p.length <= 13) ? null : 'Telefone inválido.';
  }
  if (type === 'EVP') {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(key)
      ? null : 'Chave aleatória inválida.';
  }
  return 'Tipo de chave PIX desconhecido.';
}

exports.validateWithdrawal = functions.database
  .ref('/withdrawals/{uid}/{wid}')
  .onCreate(async (snapshot, context) => {
    try {
      const wd = snapshot.val();
      if (!wd) {
        console.error('[Auditoria] Snapshot vazio — nada a validar.');
        return;
      }

      // TAREFA 3.12: ALLOWED_AMOUNTS externalizado — lê de /config/withdrawals
      // no início do handler; fallback para o default se ausente. Permite ajustar
      // valores permitidos sem redeploy da Cloud Function.
      let allowedAmounts = ALLOWED_AMOUNTS_DEFAULT;
      try {
        const cfgSnap = await admin.database().ref('config/withdrawals').once('value');
        const cfg = cfgSnap.val() || {};
        if (Array.isArray(cfg.allowedAmounts) && cfg.allowedAmounts.length > 0) {
          allowedAmounts = cfg.allowedAmounts;
        }
      } catch (cfgErr) {
        console.warn(`[Auditoria] Falha ao ler config/withdrawals: ${cfgErr.message}`);
      }

      // FIX 1.4 (b): Binding de integridade — o próprio saque deve declarar
      // o UID sob o qual foi gravado em /withdrawals/{uid}/{wid}.
      // Sem isso, um saque gravado em um path não poderia ser atribuído a outro user.
      if (wd.uid && wd.uid !== context.params.uid) {
        console.error(`[Auditoria] UID mismatch: wd.uid=${wd.uid} pathUid=${context.params.uid} (${context.params.wid})`);
        return;
      }

      try {
        const userSnap = await admin.database().ref(`users/${context.params.uid}`).once('value');
        const user = userSnap.val() || {};
        if (user.status === 'banido' || user.status === 'banned') {
          await snapshot.ref.update({
            status: 'blocked_banned_user',
            auditedAt: admin.database.ServerValue.TIMESTAMP,
          });
          await admin.database().ref(`admin/pending_withdrawals/${context.params.wid}`).remove();
          console.error(`[Auditoria] Saque ${context.params.wid} bloqueado: usuário banido.`);
          return;
        }
      } catch (userErr) {
        console.error(`[Auditoria] Falha ao consultar usuário ${context.params.uid}: ${userErr.message}`);
      }

      const problems = [];

      if (!allowedAmounts.includes(wd.amount)) {
        problems.push(`Valor fora da tabela: R$ ${wd.amount}`);
      }

      if (!VALID_PIX_TYPES.includes(wd.pixType)) {
        problems.push(`Tipo de chave PIX inválido: ${wd.pixType}`);
      } else {
        const pixErr = validatePixKey(wd.pixType, wd.pixKey);
        if (pixErr) problems.push(`Chave PIX inválida: ${pixErr}`);
      }

      if (wd.status !== 'pending') {
        problems.push(`Status inicial inesperado: ${wd.status}`);
      }

      if (!wd.uid || !wd.created_at) {
        problems.push('Dados obrigatórios ausentes (uid ou created_at).');
      }

      if (problems.length > 0) {
        await snapshot.ref.update({
          status: 'blocked_by_audit',
          auditProblems: problems,
          auditedAt: admin.database.ServerValue.TIMESTAMP,
        });
        await admin.database().ref(`admin/pending_withdrawals/${context.params.wid}`).remove();

        // Estorna o saldo para que os fundos não fiquem presos permanentemente.
        // Usa transação atômica + flag no saque para evitar estorno duplicado.
        // FIX 1.4 (a): A flag refundedByAudit passa a ser gravada DENTRO da mesma
        // transaction atômica que ajusta o saldo. Antes era gravada fora, logo, se a
        // escrita da flag falhasse após o estorno, uma nova execução estornava 2x.
        if (wd.amount && context.params.uid) {
          try {
            const uidRef = admin.database().ref(`users/${context.params.uid}`);
            await uidRef.transaction((current) => {
              const cur = current || {};
              // Não refunda se a flag já estiver setada (idempotência de re-execução)
              if (cur.refundedByAudit === true && cur.wdRefundId === context.params.wid) {
                return undefined; // aborta a transaction — nada a mudar
              }
              const bal = typeof cur.balance === 'number' ? cur.balance : 0;
              return {
                ...cur,
                balance: bal + wd.amount,
                refundedByAudit: true,
                wdRefundId: context.params.wid,
              };
            });
            console.log(`[Auditoria] Saldo estornado: R$ ${wd.amount} → ${context.params.uid}`);
          } catch (refundErr) {
            console.error(`[Auditoria] Falha ao estornar saldo: ${refundErr.message}`);
          }
        }

        console.error(
          `[Auditoria] Saque ${context.params.wid} (${wd.uid}) bloqueado:`,
          problems.join('; ')
        );
      } else {
        await snapshot.ref.update({
          auditedAt: admin.database.ServerValue.TIMESTAMP,
          audited: true,
        });
        console.log(
          `[Auditoria] Saque ${context.params.wid} (${wd.uid}) aprovado pela auditoria.`
        );
      }
    } catch (err) {
      console.error(`[Auditoria] Erro inesperado na Cloud Function: ${err.message}`);
    }
  });
