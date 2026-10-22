"use client"

import React from "react"
import { AppProvider, useApp } from "@/context/AppContext"
import { Sidebar } from "@/components/Sidebar"
import { GlobalTopBar } from "@/components/GlobalTopBar"
import { ExecutiveMatrixView } from "@/components/ExecutiveMatrixView"
import { SmartEtlView } from "@/components/SmartEtlView"
import { BankWorkbooksView } from "@/components/BankWorkbooksView"
import { ReconciliationView } from "@/components/ReconciliationView"
import { DocGeneratorView } from "@/components/DocGeneratorView"
import { BankPortalView } from "@/components/BankPortalView"
import { DrillDownDrawer } from "@/components/DrillDownDrawer"
import { RefreshCw } from "lucide-react"

function DashboardContent() {
  const { activeMenu, roleMode, isLoading } = useApp()

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#F8FAFC]">
      {/* Collapsible Left Sidebar */}
      <Sidebar />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        {/* Sticky Top Global Control Bar */}
        <GlobalTopBar />

        {/* Dynamic View Canvas */}
        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          <div className="max-w-[1600px] mx-auto w-full">
            {isLoading ? (
              <div className="h-[60vh] flex flex-col items-center justify-center space-y-3 text-slate-400">
                <RefreshCw className="w-8 h-8 animate-spin text-emerald-600" />
                <span className="text-xs font-semibold text-slate-600">
                  Memuat Data Evaluasi DU PUVA...
                </span>
              </div>
            ) : roleMode === "BANK_DU" ? (
              <BankPortalView />
            ) : (
              <>
                {activeMenu === "matrix" && <ExecutiveMatrixView />}
                {activeMenu === "etl" && <SmartEtlView />}
                {activeMenu === "workbooks" && <BankWorkbooksView />}
                {activeMenu === "reconciliation" && <ReconciliationView />}
                {activeMenu === "snapshot" && <DocGeneratorView />}
              </>
            )}
          </div>
        </main>
      </div>

      {/* Interactive Drill-Down Slide-over Drawer */}
      <DrillDownDrawer />
    </div>
  )
}

export default function Home() {
  return (
    <AppProvider>
      <DashboardContent />
    </AppProvider>
  )
}
