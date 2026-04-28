const functions = require("firebase-functions");
const admin = require("firebase-admin");
const axios = require("axios");

admin.initializeApp();

/**
 * Função para detectar o tipo de chave PIX
 */
function detectPixKeyType(key) {
    const cleanKey = key.replace(/\D/g, "");
    if (key.includes("@")) return "EMAIL";
    
    // Se tem 11 dígitos e o terceiro dígito é um '9', é muito provável que seja um Celular (DDD + 9 + Número)
    if (cleanKey.length === 11 && cleanKey[2] === '9') return "PHONE";
    if (cleanKey.length === 11) return "CPF"; // Caso contrário, tratamos como CPF
    
    if (cleanKey.length === 14) return "CNPJ";
    if (cleanKey.length === 10) return "PHONE";
    
    return "EVP"; // Chave aleatória (EVP)
}

/**
 * Cloud Function para processar o pagamento via Asaas
 */
exports.processWithdrawalV2 = functions.https.onCall(async (data, context) => {
    // 1. Verificação de Autenticação Admin
    if (!context.auth || context.auth.token.email !== 'alegomes488@gmail.com') {
        throw new functions.https.HttpsError('permission-denied', 'Apenas o administrador master pode realizar pagamentos.');
    }

    const { uid, wid, amount, pixKey, pixKeyType } = data;
    let asaasApiKey = null;

    try {
        // 2. Buscar a API Key e Ambiente do Asaas no Banco de Dados
        const snapshot = await admin.database().ref('config/gateways/asaas').once('value');
        const asaasConfig = snapshot.val() || {};
        asaasApiKey = asaasConfig.apiKey;
        const isProduction = asaasConfig.production !== false;

        if (!asaasApiKey) {
            throw new functions.https.HttpsError('failed-precondition', 'Chave API do Asaas não encontrada no Banco de Dados.');
        }

        const baseUrl = isProduction ? 'https://www.asaas.com/api/v3' : 'https://sandbox.asaas.com/api/v3';
        console.log(`Chave encontrada! Inicia com: ${asaasApiKey.substring(0, 3)}... | Ambiente: ${isProduction ? 'Produção' : 'Sandbox'}`);

        // 3. Preparar a transferência no Asaas
        // Se o frontend enviou o tipo (vencendo o detector), usamos ele.
        const pixTypeMap = {
            'Celular': 'PHONE',
            'CPF': 'CPF',
            'E-mail': 'EMAIL',
            'Aleatória': 'EVP',
            'CNPJ': 'CNPJ'
        };
        const pixType = pixTypeMap[pixKeyType] || detectPixKeyType(pixKey);
        
        console.log(`Iniciando transferência para ${pixKey} do tipo ${pixType}`);

        // Documentação Asaas: POST /v3/transfers
        const asaasResponse = await axios.post(`${baseUrl}/transfers`, {
            value: parseFloat(amount),
            pixAddressKey: pixKey,
            pixAddressKeyType: pixType,
            description: `Pagamento CyberCore IA - ID ${wid}`
        }, {
            headers: {
                'access_token': asaasApiKey,
                'Content-Type': 'application/json'
            }
        });

        if (asaasResponse.data && asaasResponse.data.id) {
            // 4. Atualizar o status para PAGO no Firebase
            await admin.database().ref(`withdrawals/${uid}/${wid}/status`).set('paid');
            await admin.database().ref(`withdrawals/${uid}/${wid}/asaasId`).set(asaasResponse.data.id);
            
            return { success: true, message: 'Pagamento processado com sucesso!', asaasId: asaasResponse.data.id };
        } else {
            throw new Error('Resposta inválida do Asaas');
        }

    } catch (error) {
        const errorData = error.response ? error.response.data : null;
        console.error('Erro no pagamento Asaas:', JSON.stringify(errorData || error.message));
        
        let errorDescription = error.message;
        if (errorData && errorData.errors && errorData.errors.length > 0) {
            errorDescription = errorData.errors[0].description;
        }

        const trace = asaasApiKey ? `(Len: ${asaasApiKey.length} | Início: ${asaasApiKey.substring(0, 4)}...)` : "(Chave Vazia)";
        return { success: false, error: errorDescription, trace: trace };
    }
});
