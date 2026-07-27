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
    {
      // Runs once per scheduled restart; no order or broker interface involved.
      name: "stock-weekly-review",
      script: "/bin/zsh",
      args: "run_weekly_review.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "15 18 * * 0",
      env: {
        TG_TOKEN: envVars.TG_TOKEN || "",
        TG_CHAT_ID: envVars.TG_CHAT_ID || "",
      },
      out_file: "logs/weekly_review_pm2_out.log",
      error_file: "logs/weekly_review_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      // 每交易日 13:20 PT（16:20 ET，收盘后）：watchlist 全池因子选股。
      // 2026-07-26 加入：把周频发现机制提速为每日，并全程自动化。
      name: "stock-daily-screener",
      script: "/bin/zsh",
      args: "run_daily_screener.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "20 13 * * 1-5",
      env: {
        TG_TOKEN: envVars.TG_TOKEN || "",
        TG_CHAT_ID: envVars.TG_CHAT_ID || "",
      },
      out_file: "logs/daily_screener_pm2_out.log",
      error_file: "logs/daily_screener_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      // 每交易日 13:35 PT：watchlist 事件雷达（52W突破/放量新高/异动）。
      // 发现型提醒，不是交易信号；覆盖没有策略路由的标的。
      name: "stock-watchlist-events",
      script: "/bin/zsh",
      args: "run_watchlist_events.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "35 13 * * 1-5",
      env: {
        TG_TOKEN: envVars.TG_TOKEN || "",
        TG_CHAT_ID: envVars.TG_CHAT_ID || "",
      },
      out_file: "logs/watchlist_events_pm2_out.log",
      error_file: "logs/watchlist_events_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      // 每交易日 14:00 PT（17:00 ET 收盘后）：IB 全池历史合并补拉。
      // 2026-07-27 加入：期货侧收敛为单一 data fetcher 后 Gateway 额度富余，
      // 本地 IB 数据从"手动按需补拉"升级为每日自动刷新——它是回测/回放/
      // alert_engine 1d 缺口填补的权威数据源。
      name: "stock-nightly-ib-refresh",
      script: "/bin/zsh",
      args: "run_nightly_ib_refresh.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "0 14 * * 1-5",
      out_file: "logs/nightly_ib_refresh_pm2_out.log",
      error_file: "logs/nightly_ib_refresh_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      // 每交易日 07:45 PT（10:45 ET，开盘75分钟后）：盘中事件雷达。
      // 2026-07-27 SHOP 逆势 +12.4%（开盘 gap +5.5%，非财报）暴露收盘雷达的
      // 时滞——新闻驱动的暴动无法从价格提前预测，但可以在启动后一小时内发现。
      name: "stock-watchlist-events-am",
      script: "/bin/zsh",
      args: "run_watchlist_events_am.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "45 7 * * 1-5",
      env: {
        TG_TOKEN: envVars.TG_TOKEN || "",
        TG_CHAT_ID: envVars.TG_CHAT_ID || "",
      },
      out_file: "logs/watchlist_events_am_pm2_out.log",
      error_file: "logs/watchlist_events_am_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
    {
      // 每月1日 06:00 PT：rejected 池复检（四策略回测+成本/walk-forward 全套验证），
      // 通过者仅推送候选报告，接入仍需人工确认。频率刻意不高于月度：
      // 反复重测同一批标的会抬高多重比较假阳性。
      name: "stock-monthly-reval",
      script: "/bin/zsh",
      args: "run_monthly_reval.sh",
      cwd: "/Users/congrenhan/Documents/quantrift_stock",
      interpreter: "none",
      autorestart: false,
      cron_restart: "0 6 1 * *",
      env: {
        TG_TOKEN: envVars.TG_TOKEN || "",
        TG_CHAT_ID: envVars.TG_CHAT_ID || "",
      },
      out_file: "logs/monthly_reval_pm2_out.log",
      error_file: "logs/monthly_reval_pm2_err.log",
      merge_logs: true,
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
