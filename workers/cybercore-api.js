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
      content: `Você é o CyberCore IA, núcleo inteligente do sistema CineCash.
Você coordena 3 agentes:
- CFO (Auditor Financeiro): saques, PIX, saldos, pagamentos
- COO (Segurança): varredura, firewall, sentinel, logs de segurança
- CMO (Growth/Nexus): crescimento, usuários, campanhas, tour

Regras:
1. Responda em PT-BR de forma técnica, direta e objetiva
2. Se for comando de sistema (abrir pasta, scan rede, etc.) execute e confirme
3. Para comandos financeiros, use [COMMAND:NAVIGATE:intercambio] para redirecionar
4. Para comandos de segurança, use [COMMAND:NAVIGATE:seguranca]
5. Seja autoritário mas profissional — você é uma IA de elite`,
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
