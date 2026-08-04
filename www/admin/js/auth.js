let loginInProgress = false;

async function login() {
    console.log("[AUTH] Iniciando login...");
    const email = document.getElementById('login-email').value.trim();
    const pass = document.getElementById('login-pass').value;

    if (!email || !pass) return showToast('Preencha e-mail e senha.', 'error');
    if (loginInProgress) return;

    loginInProgress = true;
    try {
        await auth.signInWithEmailAndPassword(email, pass);
        loginInProgress = false;
        showToast('Acesso Master concedido!', 'success');
    } catch (e) {
        loginInProgress = false;
        console.error("[AUTH] Erro:", e);
        showToast('Credenciais inválidas.', 'error');
    }
}

function logout() {
    if (auth) auth.signOut().then(() => location.reload());
}

if (auth) {
    auth.onAuthStateChanged(user => {
        const loader = document.getElementById('loader');
        if (loader) {
            loader.style.opacity = '0';
            setTimeout(() => loader.remove(), 500);
        }

        if (user && user.email === 'alegomes488@gmail.com') {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('hub-app').style.display = 'grid';
            if (typeof initRealTimeSystem === 'function') initRealTimeSystem();
        } else {
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('hub-app').style.display = 'none';
            if (user) auth.signOut();
        }
    });
}
