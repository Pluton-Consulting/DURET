"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { signOut } from "next-auth/react"
import { useState, useEffect, useRef } from "react"
import { getVisibleTabs } from "@/lib/permissions"

interface Props {
  role: string
  email: string
  name: string
}

export default function TopNav({ role, email, name }: Props) {
  const pathname = usePathname()
  const tabs = getVisibleTabs(role)
  const [showDropdown, setShowDropdown] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  const initials = name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase() || name.slice(0, 2).toUpperCase()

  useEffect(() => {
    if (!showDropdown) return
    const close = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener("mousedown", close)
    return () => document.removeEventListener("mousedown", close)
  }, [showDropdown])

  return (
    <nav
      className="sym-in"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: 64,
        background: "var(--color-surface)",
        borderBottom: "1px solid var(--color-border)",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
        display: "flex",
        alignItems: "center",
        padding: "0 28px",
        zIndex: 100,
        gap: 0,
      }}
    >
      {/* Logo */}
      <Link
        href="/accueil"
        className="sym-tap"
        style={{ marginRight: 36, flexShrink: 0, display: "flex", alignItems: "center", transition: "opacity 0.15s ease" }}
      >
        <span style={{ fontSize: 20, fontWeight: 800, color: "var(--color-primary)", letterSpacing: "-0.02em", whiteSpace: "nowrap" }}>
          Duret <span style={{ color: "var(--color-primary-mid)" }}>&amp; Sols</span>
        </span>
      </Link>

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: 2,
          flex: 1,
          alignItems: "center",
          overflowX: "auto",
          scrollbarWidth: "none",
        }}
      >
        {tabs.map((tab, i) => {
          const isActive =
            pathname === tab.href || pathname.startsWith(tab.href + "/")
          return (
            <Link
              key={tab.key}
              href={tab.href}
              className={`sym-tap sym-in sym-in-${Math.min(i + 1, 6)}`}
              style={{
                padding: "7px 14px",
                fontSize: 14,
                fontWeight: isActive ? 600 : 500,
                color: isActive
                  ? "var(--color-primary)"
                  : "var(--color-text-body)",
                borderRadius: 9,
                background: isActive
                  ? "var(--color-primary-subtle)"
                  : "transparent",
                boxShadow: isActive ? "inset 0 0 0 1px var(--color-primary-subtle)" : "none",
                transition: "background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease",
                whiteSpace: "nowrap",
                flexShrink: 0,
              }}
            >
              {tab.label}
            </Link>
          )
        })}
      </div>

      {/* Right side */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexShrink: 0,
          marginLeft: 16,
        }}
      >
        {/* Avatar + dropdown */}
        <div style={{ position: "relative" }} ref={dropRef}>
          <button
            onClick={() => setShowDropdown((v) => !v)}
            className="sym-tap"
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background:
                "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
              color: "var(--color-text-on-dark)",
              border: "none",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 700,
              boxShadow: "0 1px 3px rgba(0,0,0,0.12)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "box-shadow 0.18s ease, transform 0.18s ease",
            }}
          >
            {initials}
          </button>

          {showDropdown && (
            <div
              className="sym-pop"
              style={{
                position: "absolute",
                top: 46,
                right: 0,
                background: "var(--color-surface)",
                borderRadius: "var(--radius-card)",
                boxShadow: "var(--shadow-card-hover)",
                border: "1px solid var(--color-border)",
                minWidth: 220,
                zIndex: 200,
                overflow: "hidden",
                transformOrigin: "top right",
              }}
            >
              <div
                style={{
                  padding: "16px 18px",
                  borderBottom: "1px solid var(--color-border)",
                }}
              >
                <div
                  style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: "var(--color-text-primary)",
                  }}
                >
                  {name}
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--color-text-muted)",
                    marginTop: 2,
                  }}
                >
                  {email}
                </div>
                <span
                  className="sym-pop"
                  style={{
                    display: "inline-block",
                    marginTop: 8,
                    fontSize: 11,
                    fontWeight: 600,
                    background:
                      "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
                    color: "var(--color-text-on-dark)",
                    padding: "3px 10px",
                    borderRadius: "var(--radius-pill)",
                  }}
                >
                  {role}
                </span>
              </div>
              <div style={{ padding: 8 }}>
                <button
                  onClick={() => signOut({ callbackUrl: "/login" })}
                  className="sym-tap"
                  style={{
                    width: "100%",
                    padding: "10px 12px",
                    textAlign: "left",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 14,
                    color: "var(--color-error-text)",
                    borderRadius: 8,
                    fontWeight: 500,
                    transition: "background 0.15s ease",
                  }}
                >
                  ← Se déconnecter
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
