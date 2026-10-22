"use client"

import React from "react"
import { useApp } from "@/context/AppContext"
import {
  LayoutGrid,
  Database,
  FileSpreadsheet,
  Scale,
  FileText,
  ChevronLeft,
  ChevronRight,
  ShieldAlert,
  Building,
  CheckCircle2,
} from "lucide-react"

export const Sidebar: React.FC = () => {
  const {
    activeMenu,
    setActiveMenu,
    isSidebarCollapsed,
    toggleSidebar,
    findings,
    roleMode,
  } = useApp()

  const pendingFindingsCount = findings.filter(
    (f) => f.bi_decision_status === "OPEN" || f.bi_decision_status === "PENDING_REVIEW"
  ).length

  const menuItems = [
    {
      id: "matrix",
      label: "Executive Matrix",
      desc: "Matriks Evaluasi 21 DU & KPI",
      icon: LayoutGrid,
      badge: "21 DU",
      badgeColor: "bg-slate-800 text-slate-300",
    },
    {
      id: "etl",
      label: "Smart ETL & Data Hub",
      desc: "Multi-Source Feeders & Resolusi",
      icon: Database,
      badge: "5 Feeder",
      badgeColor: "bg-emerald-950/80 text-emerald-400 border border-emerald-500/30",
    },
    {
      id: "workbooks",
      label: "Bank Workbooks & EWS",
      desc: "Splitter 21 Lembar & Sinyal EWS",
      icon: FileSpreadsheet,
      badge: "21 Bank",
      badgeColor: "bg-slate-800 text-slate-300",
    },
    {
      id: "reconciliation",
      label: "Reconciliation Center",
      desc: "Klarifikasi Sanggahan & AI Hub",
      icon: Scale,
      badge: pendingFindingsCount > 0 ? `${pendingFindingsCount} Temuan` : "Nihil",
      badgeColor: pendingFindingsCount > 0 ? "bg-rose-950/80 text-rose-300 border border-rose-500/40" : "bg-emerald-950/80 text-emerald-300",
    },
    {
      id: "snapshot",
      label: "Snapshot & Doc Gen",
      desc: "Kunci Versi & Laporan M.02/M.01",
      icon: FileText,
      badge: "M.02/M.01",
      badgeColor: "bg-amber-950/80 text-amber-300 border border-amber-500/30",
    },
  ]

  return (
    <aside
      className={`relative z-20 flex flex-col bg-[#0F172A] border-r border-slate-800 text-slate-200 transition-all duration-300 select-none ${
        isSidebarCollapsed ? "w-20" : "w-72"
      }`}
    >
      {/* Brand Header */}
      <div className="flex items-center justify-between h-20 px-4 border-b border-slate-800/80">
        {!isSidebarCollapsed ? (
          <div className="flex items-center space-x-3 overflow-hidden">
            <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center font-bold text-white shadow-lg shadow-emerald-900/30 ring-1 ring-emerald-400/30">
              <span className="text-sm tracking-wider font-extrabold">BI</span>
            </div>
            <div className="flex flex-col min-w-0">
              <span className="font-bold text-sm tracking-wide text-white truncate flex items-center gap-1.5">
                PUVA EVAL-CORE
                <span className="text-[10px] font-semibold text-emerald-400 bg-emerald-950/80 border border-emerald-500/30 px-1.5 py-0.2 rounded">
                  v2.0
                </span>
              </span>
              <span className="text-[11px] text-slate-400 truncate">
                DPPK Bank Indonesia
              </span>
            </div>
          </div>
        ) : (
          <div className="mx-auto">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-emerald-700 flex items-center justify-center font-bold text-white shadow-md">
              <span className="text-xs font-bold">BI</span>
            </div>
          </div>
        )}

        <button
          onClick={toggleSidebar}
          title={isSidebarCollapsed ? "Perluas Sidebar" : "Lipat Sidebar"}
          className={`p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors ${
            isSidebarCollapsed ? "hidden" : "block"
          }`}
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
      </div>

      {/* Role Indicator Banner */}
      <div className="px-3 pt-4 pb-2">
        {!isSidebarCollapsed ? (
          <div className={`p-2.5 rounded-lg border text-xs flex items-center justify-between ${
            roleMode === "BI"
              ? "bg-slate-800/60 border-slate-700 text-slate-300"
              : "bg-emerald-950/40 border-emerald-500/40 text-emerald-300"
          }`}>
            <div className="flex items-center space-x-2 truncate">
              {roleMode === "BI" ? (
                <Building className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              ) : (
                <ShieldAlert className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              )}
              <span className="truncate font-medium">
                {roleMode === "BI" ? "Internal BI Command" : "Portal Bank DU"}
              </span>
            </div>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-900 font-mono text-slate-400">
              {roleMode}
            </span>
          </div>
        ) : (
          <div className="flex justify-center" title={`Mode: ${roleMode}`}>
            <div className={`w-3 h-3 rounded-full ${roleMode === "BI" ? "bg-emerald-500 ring-2 ring-emerald-500/30" : "bg-blue-500 ring-2 ring-blue-500/30"}`} />
          </div>
        )}
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 px-3 py-2 space-y-1.5 overflow-y-auto">
        {menuItems.map((item) => {
          const Icon = item.icon
          const isActive = activeMenu === item.id

          return (
            <button
              key={item.id}
              onClick={() => setActiveMenu(item.id)}
              title={isSidebarCollapsed ? `${item.label} - ${item.desc}` : undefined}
              className={`w-full flex items-center text-left rounded-xl transition-all duration-200 group relative ${
                isSidebarCollapsed
                  ? "justify-center p-3"
                  : "px-3.5 py-3 space-x-3.5"
              } ${
                isActive
                  ? "bg-gradient-to-r from-emerald-600/20 to-slate-800/80 text-white font-semibold border-l-4 border-emerald-500 shadow-sm"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
              }`}
            >
              <Icon
                className={`w-5 h-5 flex-shrink-0 transition-colors ${
                  isActive
                    ? "text-emerald-400"
                    : "text-slate-400 group-hover:text-slate-200"
                }`}
              />

              {!isSidebarCollapsed && (
                <div className="flex-1 min-w-0 flex items-center justify-between">
                  <div className="flex flex-col truncate">
                    <span className="text-xs truncate tracking-wide">
                      {item.label}
                    </span>
                    <span className="text-[10px] font-normal text-slate-500 group-hover:text-slate-400 truncate">
                      {item.desc}
                    </span>
                  </div>

                  {item.badge && (
                    <span
                      className={`ml-2 text-[10px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${item.badgeColor}`}
                    >
                      {item.badge}
                    </span>
                  )}
                </div>
              )}

              {/* Active Glow Pill */}
              {isActive && isSidebarCollapsed && (
                <div className="absolute right-1 w-1.5 h-6 bg-emerald-500 rounded-full" />
              )}
            </button>
          )
        })}
      </nav>

      {/* Expand Button when collapsed */}
      {isSidebarCollapsed && (
        <div className="p-3 border-t border-slate-800/80 flex justify-center">
          <button
            onClick={toggleSidebar}
            title="Buka Sidebar"
            className="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition-colors"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
        </div>
      )}

      {/* Footer Info */}
      {!isSidebarCollapsed && (
        <div className="p-4 border-t border-slate-800/80 text-[11px] text-slate-500 space-y-1 bg-slate-950/40">
          <div className="flex items-center space-x-1.5 text-slate-400 font-medium">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span>PADG No. 23/2024 Compliance</span>
          </div>
          <p className="text-[10px] text-slate-500 leading-tight">
            PBI No. 6 Tahun 2024 · Sistem Evaluasi Triwulanan Dealer Utama PUVA
          </p>
        </div>
      )}
    </aside>
  )
}
