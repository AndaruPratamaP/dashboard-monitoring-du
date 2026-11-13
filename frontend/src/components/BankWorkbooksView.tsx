"use client"

import React, { useState } from "react"
import { useApp } from "@/context/AppContext"
import {
  FileSpreadsheet,
  Download,
  AlertTriangle,
  CheckCircle2,
  Building2,
  Search,
  ExternalLink,
  ShieldCheck,
  TrendingDown,
} from "lucide-react"

export const BankWorkbooksView: React.FC = () => {
  const { matrix, isMasked, openDrillDown, selectedStage } = useApp()
  const [searchQuery, setSearchQuery] = useState("")

  const filtered = matrix.filter((item) => {
    const q = searchQuery.toLowerCase()
    return (
      item.bank_id.toLowerCase().includes(q) ||
      item.masked_alias.toLowerCase().includes(q) ||
      item.nama_resmi_bank.toLowerCase().includes(q)
    )
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">
            Bank Workbooks & Early Warning System (EWS)
          </h2>
        </div>

        <div className="flex flex-wrap items-center gap-2">
        <a
          href="/api/confirmation-all"
          download
          title="Workbook konfirmasi ke-21 bank (format template DPPK) dalam satu ZIP"
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold"
        >
          <Download className="w-3.5 h-3.5" />
          Unduh Semua Workbook Konfirmasi (ZIP)
        </a>
        <div className="relative w-72">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Cari bank..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>
        </div>
      </div>

      {/* Grid of 21 Bank Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((item) => {
          const displayName = isMasked ? item.masked_alias : item.nama_resmi_bank
          const isPass = item.compliance_status === "MEMENUHI"
          const isWarning = item.compliance_status === "DATA_BELUM_LENGKAP"
          const isSevere = item.compliance_status === "TIDAK_MEMENUHI"

          // Hitung parameter yang gagal
          const failedParams = Object.entries(item.passed_flags)
            .filter(([, passed]) => passed === false)
            .map(([key]) => key)

          return (
            <div
              key={item.bank_id}
              className={`bg-white rounded-xl border p-5 shadow-xs flex flex-col justify-between space-y-4 transition-all hover:shadow-md ${
                isSevere
                  ? "border-rose-300 ring-1 ring-rose-200/50"
                  : isWarning
                  ? "border-amber-300 ring-1 ring-amber-200/50"
                  : "border-slate-200"
              }`}
            >
              {/* Card Top */}
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                      {item.bank_id}
                    </span>
                    <span className="text-[11px] font-semibold text-slate-500">
                      {item.kelompok_kbmi}
                    </span>
                  </div>

                  {isPass && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      Memenuhi
                    </span>
                  )}
                  {isWarning && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-300 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3 text-amber-600" />
                      Data Belum Lengkap
                    </span>
                  )}
                  {isSevere && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-300 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3 text-rose-600" />
                      Tidak Memenuhi
                    </span>
                  )}
                </div>

                <h3 className="font-bold text-sm text-slate-900 leading-snug line-clamp-2" title={displayName}>
                  {displayName}
                </h3>
                <span className="text-[11px] text-slate-400 mt-0.5 block">
                  Alias: {item.masked_alias}
                </span>

                {/* Score Summary */}
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs bg-slate-50 p-2.5 rounded-lg border border-slate-100">
                  <div>
                    <span className="text-[10px] text-slate-400 block">Subtotal PUVA:</span>
                    <strong className="text-slate-900 font-mono text-sm">
                      {item.total_puva_score.toFixed(1)}% <span className="text-[10px] font-normal text-slate-400">/ 60%</span>
                    </strong>
                  </div>
                  <div>
                    <span className="text-[10px] text-slate-400 block">Parameter Tidak Terpenuhi:</span>
                    <strong className="text-slate-900 font-mono text-sm">
                      {failedParams.length} <span className="text-[10px] font-normal text-slate-400">/ 9</span>
                    </strong>
                  </div>
                </div>

                {/* EWS Warning Signal if any */}
                {failedParams.length > 0 ? (
                  <div className="mt-3 p-2 bg-rose-50 border border-rose-200 rounded-lg text-rose-900 text-xs flex items-center space-x-2">
                    <TrendingDown className="w-4 h-4 text-rose-600 flex-shrink-0" />
                    <div>
                      <span className="font-bold text-[11px] block">Sinyal EWS Aktif:</span>
                      <span className="text-[10px] opacity-90 leading-tight">
                        Gugur pada parameter: <strong>{failedParams.join(", ")}</strong> terhadap threshold {selectedStage}.
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="mt-3 p-2 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-900 text-xs flex items-center space-x-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                    <span className="text-[11px] font-medium text-emerald-800">
                      {isWarning
                        ? `Belum ada data: ${Object.entries(item.raw_metrics).filter(([, v]) => v === null).map(([k]) => k).join(", ")}`
                        : "Seluruh 9 parameter berada di atas ambang batas."}
                    </span>
                  </div>
                )}
              </div>

              {/* Card Footer Action */}
              <div className="pt-3 border-t border-slate-100 flex flex-wrap items-center justify-end gap-2">
                <a
                  href={`/api/export/worksheet/${item.bank_id}`}
                  download
                  title="Ringkasan hasil evaluasi bank (internal BI)"
                  className="flex items-center space-x-1.5 px-3 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold transition-colors"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  <span>Ringkasan</span>
                </a>
                <a
                  href={`/api/confirmation/${item.bank_id}`}
                  download
                  title="Workbook konfirmasi untuk dikirim ke bank (7 sheet, format template DPPK)"
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Workbook Konfirmasi</span>
                </a>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
