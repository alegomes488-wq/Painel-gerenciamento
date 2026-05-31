/**
 * CyberCore Agent: FISCAL
 * Migrated to Cloudflare Workers for distributed resilience.
 * Responsibility: Reward auditing, ROI metrics, and conversion tracking.
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    try {
      const payload = await request.json();
      const { uid, task, data } = payload;

      if (task === "process_reward") {
        return await handleReward(uid, env);
      }

      return new Response(JSON.stringify({ error: "Task not recognized" }), {
        status: 400,
        headers: { "Content-Type": "application/json" }
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" }
      });
    }
  }
};

async function handleReward(uid, env) {
  const DB_URL = env.FIREBASE_DB_URL; // e.g. https://project.firebaseio.com
  const AUTH_KEY = env.FIREBASE_AUTH_KEY; // Service Account or Database Secret

  // 1. Fetch User Data
  const userResp = await fetch(`${DB_URL}/users/${uid}.json?auth=${AUTH_KEY}`);
  const user = await userResp.json();

  if (!user) {
    return new Response(JSON.stringify({ status: "error", message: "User not found" }), {
      headers: { "Content-Type": "application/json" }
    });
  }

  // 2. Rhythm Audit
  const nowTs = Math.floor(Date.now() / 1000);
  const lastVideoTs = user.last_video_at || 0;
  let riskScore = user.risk_score || 0;

  if (nowTs - lastVideoTs < 10) {
    riskScore = Math.min(100, riskScore + 5);
    // Log Anomaly
    await fetch(`${DB_URL}/logs/security_anomalies/${uid}.json?auth=${AUTH_KEY}`, {
      method: 'POST',
      body: JSON.stringify({
        timestamp: Date.now(),
        reason: "FAST_REWARD_CLAIM_WORKER",
        details: `Intervalo de ${nowTs - lastVideoTs}s detectado no Edge.`
      })
    });
  }

  // 3. Calculate Reward
  const rewardValue = 0.10;
  const newBalance = Math.round(( (user.balance || 0) + rewardValue ) * 100) / 100;
  const newWatched = (user.videosWatched || 0) + 1;

  const updateData = {
    balance: newBalance,
    videosWatched: newWatched,
    last_video_at: nowTs,
    last_reward_ts: Date.now(),
    risk_score: riskScore
  };

  // 4. Referral Logic (Conversion Fiscal)
  if (newWatched === 15) {
    const sponsorUid = user.referredBy;
    if (sponsorUid) {
      // Get sponsor data
      const sponsorResp = await fetch(`${DB_URL}/users/${sponsorUid}.json?auth=${AUTH_KEY}`);
      const sponsorData = await sponsorResp.json();
      if (sponsorData) {
        const currentValid = sponsorData.validReferrals || 0;
        await fetch(`${DB_URL}/users/${sponsorUid}.json?auth=${AUTH_KEY}`, {
          method: 'PATCH',
          body: JSON.stringify({ validReferrals: currentValid + 1 })
        });
        // Log Referral Bonus
        await fetch(`${DB_URL}/logs/referrals.json?auth=${AUTH_KEY}`, {
          method: 'POST',
          body: JSON.stringify({
            sponsor: sponsorUid,
            referral: uid,
            action: "BONUS_CONVERTED_WORKER",
            timestamp: Date.now()
          })
        });
      }
    }
  }

  // 5. Apply Updates
  await fetch(`${DB_URL}/users/${uid}.json?auth=${AUTH_KEY}`, {
    method: 'PATCH',
    body: JSON.stringify(updateData)
  });

  // 6. Global Stats
  // Note: Atomic increment is hard with REST, but we simulate hits
  // In production, use a transaction or a separate counter service

  return new Response(JSON.stringify({
    status: "success",
    reward: rewardValue,
    new_balance: newBalance,
    agent: "fiscal_worker_edge",
    location: "cloudflare_distributed"
  }), {
    headers: { "Content-Type": "application/json" }
  });
}
