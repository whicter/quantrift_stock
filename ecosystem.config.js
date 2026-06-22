// pm2 ecosystem — quantrift_stock 告警引擎
// 用法：
//   pm2 start ecosystem.config.js          # 启动（模拟盘 4002）
//   pm2 start ecosystem.config.js --env live  # 启动（实盘 4001）
//   pm2 stop stock-alert
//   pm2 restart stock-alert
//   pm2 logs stock-alert --lines 50

// 手动解析 .env（不依赖 npm dotenv）
const fs = require("fs");
const path = require("path");
const envPath = path.join(__dirname, ".env");
const envVars = {};
if (fs.existsSync(envPath)) {
  fs.readFileSync(envPath, "utf8").split("\n").forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) return;
    const idx = trimmed.indexOf("=");
    if (idx === -1) return;
    envVars[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
  });
}

module.exports = {
  apps: [
    {
      name: "stock-alert",
      script: "/opt/homebrew/bin/python3.11",
      args: "alert_engine.py",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",

      // 环境变量（从 .env 读入，pm2 自动注入）
      env: {
        ALERT_PORT:        "4002",
        TT_USERNAME:       envVars.TT_USERNAME       || "",
        TT_PASSWORD:       envVars.TT_PASSWORD       || "",
        TT_REMEMBER_TOKEN: envVars.TT_REMEMBER_TOKEN || "",
        TG_TOKEN:          envVars.TG_TOKEN          || "",
        TG_CHAT_ID:        envVars.TG_CHAT_ID        || "",
      },
      env_live: {
        // pm2 start ecosystem.config.js --env live 时切换实盘端口
        TT_USERNAME:       envVars.TT_USERNAME       || "",
        TT_PASSWORD:       envVars.TT_PASSWORD       || "",
        TT_REMEMBER_TOKEN: envVars.TT_REMEMBER_TOKEN || "",
        TG_TOKEN:          envVars.TG_TOKEN          || "",
        TG_CHAT_ID:        envVars.TG_CHAT_ID        || "",
        ALERT_PORT: "4001",
      },

      // 崩溃后自动重启，连续失败超过 5 次停止（避免死循环）
      autorestart:    true,
      max_restarts:   5,
      restart_delay:  10000,   // 重启间隔 10s

      // 日志
      out_file:  "logs/pm2_out.log",
      error_file: "logs/pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
