// pm2 ecosystem — quantrift_stock 告警引擎
// 用法：
//   pm2 start ecosystem.config.js          # 启动（模拟盘 4002）
//   pm2 start ecosystem.config.js --env live  # 启动（实盘 4001）
//   pm2 stop stock-alert
//   pm2 restart stock-alert
//   pm2 logs stock-alert --lines 50

require("dotenv").config();   // 自动读取项目根目录的 .env

module.exports = {
  apps: [
    {
      name: "stock-alert",
      script: "/opt/homebrew/bin/python3.11",
      args: "alert_engine.py --port 4002",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",

      // 环境变量（从 .env 读入，pm2 自动注入）
      env: {
        TT_USERNAME:       process.env.TT_USERNAME       || "",
        TT_PASSWORD:       process.env.TT_PASSWORD       || "",
        TT_REMEMBER_TOKEN: process.env.TT_REMEMBER_TOKEN || "",
        TG_TOKEN:          process.env.TG_TOKEN          || "",
        TG_CHAT_ID:        process.env.TG_CHAT_ID        || "",
      },
      env_live: {
        // pm2 start --env live 时切换实盘端口
        TT_USERNAME:       process.env.TT_USERNAME       || "",
        TT_PASSWORD:       process.env.TT_PASSWORD       || "",
        TT_REMEMBER_TOKEN: process.env.TT_REMEMBER_TOKEN || "",
        TG_TOKEN:          process.env.TG_TOKEN          || "",
        TG_CHAT_ID:        process.env.TG_CHAT_ID        || "",
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
