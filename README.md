---
title: CineCash Brasil Hexa
emoji: 🚀
colorFrom: green
colorTo: yellow
sdk: docker
pinned: false
---

# 🇧🇷 CineCash: Brasil Hexa 🚀

Welcome to **CineCash Brasil Hexa**, a futuristic play-to-earn and gamification platform where football passion meets real rewards. This project combines Cyberpunk aesthetics with the Brazilian National Team pride to create a unique high-fidelity experience.

## 🌟 Futuristic Visual Identity
Our interface is inspired by the Brazilian flag with a technological "Glassmorphism" twist:
- **Selection Green:** `#006437`
- **Gold Yellow:** `#FFD700`
- **Stellar Blue:** `#002776`
- **Font:** Sora (Modern & Clean)

## 🎮 GameCash: Play & Earn
The platform features integrated mini-games connected to the real balance:
- **Flappy Canarinho:** Skill-based game with tiered rewards.
- **Hexa Memory:** Cognitive game featuring football legends.
- **Dynamic Milestones:** Watch clips/ads to reach withdrawal goals.

## 💰 Rewards & Referral System
- **Referral Program:** R$ 0.20 per active user + R$ 1.50 "Super Bonus" for every 7 valid invites.
- **Daily Bonus:** Weekend-specific rewards (R$ 0.20) for active operators.
- **Withdrawals via Asaas:** Secure PIX integration for fast payouts.

## 🛡️ "VAR" Security System
Advanced anti-fraud measures powered by our proprietary "VAR" logic:
- **Risk Scoring:** Real-time analysis of IP consistency and action velocity.
- **Nexus Agent:** Deep telemetry for behavioral auditing.
- **Session Locking:** Automatic logout on blur or tab refresh to prevent automated manipulation.

## 🛠️ Tech Stack
- **Backend:** FastAPI (Python 3.10)
- **Frontend:** SPA (HTML5, CSS3, JavaScript)
- **Database:** Firebase Realtime Database
- **Payments:** Asaas API Integration
- **AI Assistant:** "Agente Canarinho" (Groq API + Local FAQ Memory)

## 🚀 Deployment (Hugging Face Spaces)

### Required Secrets
Ensure the following Secrets are configured in your Space settings:
- `FIREBASE_SERVICE_ACCOUNT`: Full Service Account JSON.
- `ASAAS_API_KEY`: Your Asaas production/sandbox key.
- `GROQ_API_KEY`: API key for the AI Assistant.

### Local Development
```bash
docker build -t cinecash-brasil-hexa .
docker run -p 7860:7860 cinecash-brasil-hexa
```

---
*CineCash - Technology at the service of the fans on the road to Hexa!* 🏆
