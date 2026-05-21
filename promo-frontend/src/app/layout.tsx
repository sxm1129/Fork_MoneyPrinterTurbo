import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PromoStudio — 抖音推广视频批量生成",
  description:
    "AI 驱动的抖音直播推广视频批量生成工作台。一键优化口播稿、生成多风格变体、批量合成高质量短视频。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        {/* ── 顶部导航栏 ── */}
        <nav
          style={{
            position: "sticky",
            top: 0,
            zIndex: 50,
            height: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 32px",
            background: "rgba(10, 10, 15, 0.8)",
            backdropFilter: "blur(16px)",
            borderBottom: "1px solid var(--border-subtle)",
          }}
        >
          <a
            href="/"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              textDecoration: "none",
            }}
          >
            <span
              style={{
                fontSize: 22,
                fontWeight: 900,
                letterSpacing: -0.5,
              }}
              className="accent-gradient-text"
            >
              PromoStudio
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: "var(--accent-secondary)",
                background: "rgba(108, 92, 231, 0.12)",
                padding: "2px 8px",
                borderRadius: 6,
              }}
            >
              BETA
            </span>
          </a>

          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <a
              href="/create"
              className="btn btn-primary"
              style={{ padding: "8px 20px", fontSize: 13 }}
            >
              ✨ 新建任务
            </a>
          </div>
        </nav>

        {/* ── 主内容 ── */}
        <main style={{ minHeight: "calc(100vh - 64px)" }}>{children}</main>
      </body>
    </html>
  );
}
