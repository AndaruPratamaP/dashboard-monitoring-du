"use client"

import React from "react"
import { useApp } from "@/context/AppContext"
import { ThresholdStage } from "@/types"
import {
  Calendar,
  Layers,
  Eye,
  EyeOff,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react"

export const GlobalTopBar: React.FC = () => {
  const {
    periods,
    activePeriod,
    changePeriod,
    selectedStage,
    changeStage,
    isMasked,
    toggleMasked,
    isRecalculating,
    refreshData,
  } = useApp()

  const stages: { key: ThresholdStage; label: string }[] = [
    { key: "EARLY", label: "Early State" },
    { key: "INTERMEDIATE", label: "Intermediate" },
    { key: "END_STATE", label: "End-State" },
  ]

  return (
    <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-slate-200/80 shadow-sm transition-all px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left Side: Period & Threshold Stage Selector */}
        <div className="flex flex-wrap items-center gap-3">
          {/* 1. Selector Periode */}
          <div className="flex items-center bg-slate-100/90 border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs text-slate-700 shadow-xs">
            <Calendar className="w-3.5 h-3.5 text-slate-500 mr-2 flex-shrink-0" />
            <select
              value={activePeriod?.id ?? ""}
              onChange={(e) => changePeriod(Number(e.target.value))}
              className="bg-transparent font-semibold text-slate-800 cursor-pointer focus:outline-none pr-1"
            >
              {periods.length === 0 && <option value="">Belum ada periode</option>}
              {periods.map((p) => {
                const [year, q] = p.triwulan.split("-Q")
                const roman = ["I", "II", "III", "IV"][Number(q) - 1] || q
                return (
                  <option key={p.id} value={p.id}>
                    Triwulan {roman} - {year}
                  </option>
                )
              })}
            </select>
          </div>

          {/* 2. Selector Tahap Threshold (Real-time Recalculation) */}
          <div className="flex items-center bg-slate-100/90 p-1 rounded-lg border border-slate-200/80">
            <div className="flex space-x-1">
              {stages.map((st) => {
                const isSelected = selectedStage === st.key
                return (
                  <button
                    key={st.key}
                    onClick={() => changeStage(st.key)}
                    disabled={isRecalculating}
                    title={st.label}
                    className={`px-3 py-1 text-xs rounded-md font-medium transition-all duration-150 flex items-center space-x-1.5 ${
                      isSelected
                        ? "bg-emerald-600 text-white shadow-xs font-semibold"
                        : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/70"
                    } ${isRecalculating ? "opacity-70 cursor-wait" : ""}`}
                  >
                    <span>{st.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {isRecalculating && (
            <div className="flex items-center text-xs text-emerald-600 font-medium animate-pulse">
              <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" />
              <span>Menghitung Ulang...</span>
            </div>
          )}
        </div>

        {/* Right Side: Privacy Masking Switch */}
        <div className="flex flex-wrap items-center gap-3">
          {/* 3. Privacy Masking Switch */}
          <button
            onClick={toggleMasked}
            title={isMasked ? "Nama Asli Bank" : "Mode Alias"}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium transition-all ${
              isMasked
                ? "bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200"
                : "bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100 shadow-xs"
            }`}
          >
            {isMasked ? (
              <>
                <EyeOff className="w-3.5 h-3.5 text-slate-500" />
                <span>Mode Alias</span>
              </>
            ) : (
              <>
                <Eye className="w-3.5 h-3.5 text-amber-600" />
                <span>Nama Resmi</span>
              </>
            )}
          </button>

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
