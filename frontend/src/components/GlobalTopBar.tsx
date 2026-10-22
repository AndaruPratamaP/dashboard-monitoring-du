"use client"

import React from "react"
import { useApp } from "@/context/AppContext"
import { ThresholdStage, RoleMode } from "@/types"
import {
  Calendar,
  Layers,
  Eye,
  EyeOff,
  UserCheck,
  Building2,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react"

export const GlobalTopBar: React.FC = () => {
  const {
    selectedPeriod,
    setSelectedPeriod,
    selectedStage,
    changeStage,
    isMasked,
    toggleMasked,
    roleMode,
    setRoleMode,
    simulatedBankId,
    setSimulatedBankId,
    banks,
    isRecalculating,
    refreshData,
  } = useApp()

  const stages: { key: ThresholdStage; label: string; badge: string }[] = [
    { key: "EARLY", label: "Early State", badge: "80% / 50%" },
    { key: "INTERMEDIATE", label: "Intermediate", badge: "85% / 70%" },
    { key: "END_STATE", label: "End-State", badge: "90% / 80%" },
  ]

  return (
    <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-slate-200/80 shadow-sm transition-all px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left Side: Period & Threshold Stage Selector */}
        <div className="flex flex-wrap items-center gap-3">
          {/* 1. Selector Periode */}
          <div className="flex items-center bg-slate-100/90 border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs text-slate-700 shadow-xs">
            <Calendar className="w-3.5 h-3.5 text-slate-500 mr-2 flex-shrink-0" />
            <span className="text-[11px] text-slate-400 mr-1.5 font-medium">Periode:</span>
            <select
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(e.target.value)}
              className="bg-transparent font-semibold text-slate-800 cursor-pointer focus:outline-none pr-1"
            >
              <option value="2026-Q2">Triwulan II - 2026 (Aktif)</option>
              <option value="2026-Q1">Triwulan I - 2026</option>
              <option value="2025-Q4">Triwulan IV - 2025</option>
            </select>
          </div>

          {/* 2. Selector Tahap Threshold (Real-time Recalculation) */}
          <div className="flex items-center bg-slate-100/90 p-1 rounded-lg border border-slate-200/80">
            <div className="flex items-center px-2 text-slate-500 text-[11px] font-medium mr-1 hidden sm:flex">
              <Layers className="w-3.5 h-3.5 mr-1 text-emerald-600" />
              <span>Threshold:</span>
            </div>
            <div className="flex space-x-1">
              {stages.map((st) => {
                const isSelected = selectedStage === st.key
                return (
                  <button
                    key={st.key}
                    onClick={() => changeStage(st.key)}
                    disabled={isRecalculating}
                    title={`Pindah ke tahap ${st.label}`}
                    className={`px-3 py-1 text-xs rounded-md font-medium transition-all duration-150 flex items-center space-x-1.5 ${
                      isSelected
                        ? "bg-emerald-600 text-white shadow-xs font-semibold"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/70"
                    } ${isRecalculating ? "opacity-70 cursor-wait" : ""}`}
                  >
                    <span>{st.label}</span>
                    <span
                      className={`text-[9px] px-1 py-0.2 rounded font-mono ${
                        isSelected
                          ? "bg-emerald-700 text-emerald-100"
                          : "bg-slate-200 text-slate-500"
                      }`}
                    >
                      {st.badge}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {isRecalculating && (
            <div className="flex items-center text-xs text-emerald-600 font-medium animate-pulse">
              <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" />
              <span>Menghitung Ulang Skor...</span>
            </div>
          )}
        </div>

        {/* Right Side: Privacy Masking Switch & Role Switcher */}
        <div className="flex flex-wrap items-center gap-3">
          {/* 3. Privacy Masking Switch */}
          <button
            onClick={toggleMasked}
            title={isMasked ? "Klik untuk menampilkan Nama Asli Bank" : "Klik untuk menyamarkan nama (Mode Alias)"}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${
              isMasked
                ? "bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200"
                : "bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100 shadow-xs"
            }`}
          >
            {isMasked ? (
              <>
                <EyeOff className="w-3.5 h-3.5 text-slate-500" />
                <span>Mode Alias: <strong className="font-semibold text-slate-800">Bank A - U</strong></span>
              </>
            ) : (
              <>
                <Eye className="w-3.5 h-3.5 text-amber-600" />
                <span>Nama Terbuka: <strong className="font-semibold text-amber-900">Nama Resmi PT</strong></span>
              </>
            )}
          </button>

          {/* 4. Interactive Role Switcher */}
          <div className="flex items-center bg-slate-900 text-white rounded-lg p-1 border border-slate-800 shadow-sm">
            <button
              onClick={() => setRoleMode("BI")}
              className={`flex items-center space-x-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all ${
                roleMode === "BI"
                  ? "bg-emerald-600 text-white shadow-xs font-semibold"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              <Building2 className="w-3.5 h-3.5" />
              <span>Internal BI (DPPK)</span>
            </button>

            <button
              onClick={() => setRoleMode("BANK_DU")}
              className={`flex items-center space-x-1.5 px-3 py-1 rounded-md text-xs font-medium transition-all ${
                roleMode === "BANK_DU"
                  ? "bg-emerald-600 text-white shadow-xs font-semibold"
                  : "text-slate-300 hover:text-white"
              }`}
            >
              <UserCheck className="w-3.5 h-3.5" />
              <span>Portal Bank DU</span>
            </button>
          </div>

          {/* Bank Selection Dropdown when in Bank DU Simulation Mode */}
          {roleMode === "BANK_DU" && (
            <div className="flex items-center bg-emerald-50 border border-emerald-300 rounded-lg px-2.5 py-1.5 text-xs text-emerald-900 shadow-xs animate-in fade-in slide-in-from-top-1 duration-200">
              <span className="text-[11px] font-semibold text-emerald-700 mr-2">Simulasi:</span>
              <select
                value={simulatedBankId}
                onChange={(e) => setSimulatedBankId(e.target.value)}
                className="bg-transparent font-bold text-emerald-950 cursor-pointer focus:outline-none"
              >
                {banks.map((b) => (
                  <option key={b.bank_id} value={b.bank_id}>
                    {isMasked ? `${b.masked_alias} (${b.bank_id})` : `${b.nama_resmi_bank} (${b.masked_alias})`}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Refresh Manual Button */}
          <button
            onClick={refreshData}
            title="Muat Ulang Data dari Server"
            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  )
}
