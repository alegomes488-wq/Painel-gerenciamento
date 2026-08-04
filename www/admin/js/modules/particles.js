/**
 * Sistema de Micro Partículas Premium - Painel Admin
 * Estilo Nebula / Digital Texture
 */
(function() {
    const canvas = document.getElementById('micro-particles-canvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let W, H, particles = [];
    const mouse = { x: -999, y: -999 };

    const COLORS = [
        'rgba(59, 130, 246, ',  // Blue (Primary)
        'rgba(139, 92, 246, ',  // Purple (Accent)
        'rgba(6, 182, 212, ',   // Cyan
        'rgba(255, 255, 255, '  // White
    ];

    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = window.innerHeight;
        initParticles();
    }

    function initParticles() {
        particles = [];
        const count = Math.floor((W * H) / 10000); // Densidade baseada na tela

        for (let i = 0; i < count; i++) {
            particles.push({
                x: Math.random() * W,
                y: Math.random() * H,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                r: Math.random() * 1.5 + 0.5,
                colorPrefix: COLORS[Math.floor(Math.random() * COLORS.length)],
                phase: Math.random() * Math.PI * 2,
                speed: 0.01 + Math.random() * 0.02
            });
        }
    }

    function animate() {
        ctx.clearRect(0, 0, W, H);

        // Ativa modo lighter para brilho aditivo em áreas densas
        ctx.globalCompositeOperation = 'lighter';

        const time = Date.now() * 0.001;

        for (let i = 0; i < particles.length; i++) {
            const p = particles[i];

            // Movimento browniano leve
            p.x += p.vx + Math.sin(time + p.phase) * 0.2;
            p.y += p.vy + Math.cos(time + p.phase) * 0.2;

            // Loop nas bordas
            if (p.x < 0) p.x = W;
            if (p.x > W) p.x = 0;
            if (p.y < 0) p.y = H;
            if (p.y > H) p.y = 0;

            // Reação ao mouse
            const dx = mouse.x - p.x;
            const dy = mouse.y - p.y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < 150) {
                const force = (150 - dist) / 150;
                p.x -= dx * force * 0.02;
                p.y -= dy * force * 0.02;
            }

            // Opacidade pulsante
            const alpha = 0.1 + 0.4 * Math.sin(time * 0.5 + p.phase);

            ctx.fillStyle = p.colorPrefix + alpha + ')';
            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fill();

            // Glow ocasional para partículas brancas
            if (p.colorPrefix === COLORS[3] && Math.random() > 0.998) {
                ctx.save();
                ctx.shadowBlur = 10;
                ctx.shadowColor = '#fff';
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r * 1.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            }
        }

        ctx.globalCompositeOperation = 'source-over';
        requestAnimationFrame(animate);
    }

    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', e => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
    });

    resize();
    animate();
})();
