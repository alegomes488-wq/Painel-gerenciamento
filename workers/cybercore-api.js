// CyberCore IA — Cloudflare Worker
// Usa Groq API (llama-3.3-70b) com memória de conversa
// Deploy: copiar para Cloudflare Dashboard > Workers & Pages > cybercore-api > Editar código

// GROQ_API_KEY deve ser configurada como Variável de Ambiente (secret) no Cloudflare Worker

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

// Memória em cache global (volátil — por request)
const memoryStore = {};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // GET /chat?msg=... (legado, admin terminal)
    if (request.method === 'GET' && path === '/chat') {
      const msg = url.searchParams.get('msg') || '';
      if (!msg) {
        return json({ error: 'msg parameter required' }, 400);
      }
      const answer = await askGroq(msg, [], env.GROQ_API_KEY);
      return json({ resposta: answer });
    }

    // POST /ai/chat (novo, full-feature)
    if (request.method === 'POST' && path === '/ai/chat') {
      try {
        const body = await request.json();
        const prompt = body.prompt || body.msg || '';
        const history = body.history || [];
        const uid = body.uid || 'anonymous';

        if (!prompt) {
          return json({ error: 'prompt or msg required' }, 400);
        }

        if (!memoryStore[uid]) {
          memoryStore[uid] = [];
        }
        memoryStore[uid].push({ role: 'user', content: prompt });

        const fullHistory = [...memoryStore[uid]];
        const answer = await askGroq(prompt, fullHistory.slice(-15), env.GROQ_API_KEY);

        memoryStore[uid].push({ role: 'assistant', content: answer });
        if (memoryStore[uid].length > 30) {
          memoryStore[uid] = memoryStore[uid].slice(-30);
        }

        return json({ answer, history: fullHistory.slice(-15) });
      } catch (e) {
        return json({ answer: `Erro no Worker: ${e.message}` });
      }
    }

    // POST /chat (alternate)
    if (request.method === 'POST' && path === '/chat') {
      try {
        const body = await request.json();
        const msg = body.msg || body.prompt || '';
        if (!msg) return json({ error: 'msg required' }, 400);
        const history = body.history || [];
        const answer = await askGroq(msg, history, env.GROQ_API_KEY);
        return json({ resposta: answer });
      } catch (e) {
        return json({ resposta: `Erro: ${e.message}` });
      }
    }

    // Health check
    if (path === '/health') {
      return json({
        status: 'online',
        service: 'CyberCore IA Worker',
        provider: 'Groq',
        model: 'llama-3.3-70b-versatile',
        hasKey: !!env.GROQ_API_KEY,
      });
    }

    return json({ error: 'Not Found' }, 404);
  },
};

async function askGroq(prompt, history = [], apiKey) {
  if (!apiKey) {
    return 'GROQ_API_KEY não configurada. Adicione como secret no Worker.';
  }

  const messages = [
    {
      role: 'system',
      content: `Você é o Agente Nexus do CineCash, assistente virtual especializado na plataforma.

REGRAS GERAIS:
1. Responda SEMPRE em português brasileiro, de forma amigável, didática e motivacional.
2. Trate o usuário com respeito e paciência, como um tutor.
3. NUNCA invente informações — se não souber, diga que vai verificar.
4. Use [COMMAND:NAVIGATE:inicio], [COMMAND:NAVIGATE:intercambio], [COMMAND:NAVIGATE:convites] ou [COMMAND:NAVIGATE:historico] para sugerir navegação.
5. Use [COMMAND:START_TOUR] para iniciar o tour guiado.

PLATAFORMA CINECASH:
- 4 abas principais: Início (dashboard), Intercâmbio (saques), Convites (indicações), Histórico (transações)
- Anúncios: o usuário clica em "Processar Anúncios" no dashboard para validar campanhas via IA
- Saldo: exibido no topo, acumulado por anúncios, bônus diário e indicações
- Saque mínimo: R$ 0,50 via PIX
- Valores de saque: R$ 0,50 | R$ 3,00 | R$ 5,00 | R$ 10,00 | R$ 50,00

BÔNUS DIÁRIO:
- Valor: R$ 0,20
- Disponível apenas em finais de semana (sábado e domingo)
- 1 vez por dia, botão "COLETAR BÔNUS" na aba Início

METAS (progresso de anúncios → valor de saque liberado):
- 150 anúncios → R$ 0,50
- 900 anúncios → R$ 3,00
- 1500 anúncios → R$ 5,00
- 3000 anúncios → R$ 10,00
- 15000 anúncios → R$ 50,00

SISTEMA DE CONVITES (INDICAÇÕES):
- Cada amigo convidado que assistir 25 anúncios rende R$ 0,20
- A cada 5 amigos válidos, bônus extra de R$ 1,00
- O link de convite fica na aba Convites

TIPOS DE CHAVE PIX:
- CPF: 11 dígitos
- CNPJ: 14 dígitos
- E-mail: formato padrão
- Telefone: 10 a 13 dígitos (com DDD)
- Chave aleatória (EVP): formato UUID`,
    },
    ...history.map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content || m.text || '',
    })),
    { role: 'user', content: prompt },
  ];

  try {
    const resp = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'llama-3.3-70b-versatile',
        messages,
        temperature: 0.7,
        max_tokens: 1024,
      }),
    });

    const data = await resp.json();
    return data.choices?.[0]?.message?.content || 'Sem resposta do modelo.';
  } catch (e) {
    return `Erro na consulta Groq: ${e.message}`;
  }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
