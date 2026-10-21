(function initTelemetryClient() {
    const BASE_URL = typeof BRASILHEXA_BACKEND_URL !== 'undefined' ? BRASILHEXA_BACKEND_URL : '';
    const SSE_URL = BASE_URL + '/api/telemetry/stream';
    const RECENTES_URL = BASE_URL + '/api/telemetry/recentes?limite=10';
    let eventSource = null, reconnectTimeout = null, RECONNECT_DELAY = 5000;
    function dispatchTelemetryEvent(d){ try{ window.dispatchEvent(new CustomEvent('cybercore:agent-telemetry',{detail:d})); }catch(e){} }
    function onTelemetry(e){
        if(!e || !e.data) return;
        try{ dispatchTelemetryEvent(JSON.parse(e.data)); }catch(err){}
    }
    function conectarSSE(){
        // Prefixo vazio = mesma origem; a conexão deve acontecer mesmo assim.
        if(typeof EventSource === 'undefined'){ reconnectTimeout=setTimeout(conectarSSE,RECONNECT_DELAY); return; }
        if(eventSource) eventSource.close();
        try{
            eventSource = new EventSource(SSE_URL,{withCredentials:false});
            eventSource.onopen = function(){ if(reconnectTimeout){ clearTimeout(reconnectTimeout); reconnectTimeout=null; } buscarEventosRecentes(); };
            // O backend emite eventos nomeados ("event: telemetry"); onmessage
            // sozinho não os recebe.
            eventSource.addEventListener('telemetry', onTelemetry);
            eventSource.onmessage = onTelemetry;
            eventSource.onerror = function(err){ if(eventSource){ eventSource.close(); eventSource=null; } reconnectTimeout=setTimeout(conectarSSE,RECONNECT_DELAY); };
        }catch(e){ reconnectTimeout=setTimeout(conectarSSE,RECONNECT_DELAY); }
    }
    async function buscarEventosRecentes(){
        try{
            const idToken = (typeof auth !== 'undefined' && auth && auth.currentUser) ? await auth.currentUser.getIdToken() : '';
            if(!idToken) return;
            const resp = await fetch(RECENTES_URL,{headers:{'Authorization':'Bearer '+idToken,'Content-Type':'application/json'}});
            if(!resp.ok) return; const d=await resp.json(); (d.eventos||[]).forEach(dispatchTelemetryEvent);
        }catch(e){}
    }
    function iniciar(){
        if(typeof BRASILHEXA_BACKEND_URL === 'undefined'){ setTimeout(iniciar,500); return; }
        conectarSSE();
        if(typeof auth !== 'undefined' && auth && typeof auth.onAuthStateChanged === 'function'){
            auth.onAuthStateChanged(user => { if(user) buscarEventosRecentes(); });
        } else {
            setTimeout(buscarEventosRecentes, 2000);
        }
    }
    if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',iniciar); else iniciar();
})();
