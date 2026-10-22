"use client"

import React, { useEffect } from "react"
import { useApp } from "@/context/AppContext"
import {
  X,
  ShieldCheck,
  AlertTriangle,
  FileSpreadsheet,
  ExternalLink,
  BookOpen,
  Calendar,
  Hash,
  Activity,
  ArrowRight,
  TrendingDown,
  CheckCircle,
} from "lucide-react"

export const DrillDownDrawer: React.FC = () => {
  const {
    drillDown,
    isDrawerOpen,
    closeDrillDown,
    isMasked,
    setActiveMenu,
  } = useApp()

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDrillDown()
    }
    if (isDrawerOpen) {
      window.addEventListener("keydown", handleKeyDown)
    }
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [isDrawerOpen, closeDrillDown])

  if (!isDrawerOpen || !drillDown) return null

  const displayName = isMasked ? drillDown.bankAlias : drillDown.bankOfficialName
  const failedItems = drillDown.failedTransactions || []

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop overlay */}
      <div
        onClick={closeDrillDown}
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-2xl bg-white shadow-2xl flex flex-col border-l border-slate-200 animate-in slide-in-from-right duration-300">
          
          {/* Header */}
          <div className="px-6 py-5 bg-[#0F172A] text-white flex items-start justify-between border-b border-slate-800">
            <div>
              <div className="flex items-center space-x-2 text-xs text-slate-400 mb-1">
                <span className="font-mono text-emerald-400 font-bold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-500/30">
                  {drillDown.bankId}
                </span>
                <span>·</span>
                <span className="text-slate-300">{drillDown.kbmi}</span>
                <span>·</span>
                <span className="text-slate-300">Tahap: {drillDown.stage}</span>
              </div>
              <h2 className="text-lg font-bold text-white tracking-wide leading-tight">
                {displayName}
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {drillDown.paramCode} — {drillDown.paramName}
              </p>
            </div>

            <button
              onClick={closeDrillDown}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Drawer Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 text-slate-800">
            
            {/* 1. Status Evaluation Banner */}
            <div
              className={`p-4 rounded-xl border flex items-center justify-between shadow-xs ${
                drillDown.isPassed
                  ? "bg-emerald-50/80 border-emerald-200 text-emerald-900"
                  : "bg-rose-50/80 border-rose-200 text-rose-900"
              }`}
            >
              <div className="flex items-center space-x-3">
                <div
                  className={`p-2 rounded-lg ${
                    drillDown.isPassed ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"
                  }`}
                >
                  {drillDown.isPassed ? (
                    <ShieldCheck className="w-6 h-6" />
                  ) : (
                    <AlertTriangle className="w-6 h-6" />
                  )}
                </div>
                <div>
                  <div className="font-bold text-sm">
                    {drillDown.isPassed ? "MEMENUHI AMBANG BATAS (LOLOS)" : "DI BAWAH AMBANG BATAS (GUGUR / TEMUAN)"}
                  </div>
                  <div className="text-xs opacity-80 mt-0.5">
                    {drillDown.isPassed
                      ? `Capaian ${drillDown.rawRate}% melampaui batas minimal tahap ${drillDown.stage} (>= ${drillDown.threshold}%)`
                      : `Capaian ${drillDown.rawRate}% di bawah batas minimal tahap ${drillDown.stage} (>= ${drillDown.threshold}%)`}
                  </div>
                </div>
              </div>

              <div className="text-right">
                <div className="text-xs font-semibold uppercase tracking-wider opacity-70">Skor Diperoleh</div>
                <div className="text-xl font-extrabold">
                  {drillDown.score.toFixed(2)}% <span className="text-xs font-normal opacity-70">/ {drillDown.weight.toFixed(1)}%</span>
                </div>
              </div>
            </div>

            {/* 2. Key Metrics 3-Card Grid */}
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 text-center">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                  Realisasi Mentah
                </span>
                <span className="text-2xl font-black text-slate-900">
                  {drillDown.rawRate}%
                </span>
                <span className="text-[10px] text-slate-400 block mt-0.5">sebelum bobot</span>
              </div>

              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 text-center">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                  Batas Threshold
                </span>
                <span className="text-2xl font-black text-slate-900">
                  {drillDown.threshold}%
                </span>
                <span className="text-[10px] text-slate-400 block mt-0.5">{drillDown.stage}</span>
              </div>

              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/90 text-center">
                <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-1">
                  Bobot Indikator
                </span>
                <span className="text-2xl font-black text-emerald-700">
                  {drillDown.weight}%
                </span>
                <span className="text-[10px] text-slate-400 block mt-0.5">maksimal PUVA</span>
              </div>
            </div>

            {/* 3. Regulatory Rule Reference */}
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 text-xs text-slate-700 space-y-1.5">
              <div className="flex items-center space-x-1.5 text-slate-900 font-semibold">
                <BookOpen className="w-4 h-4 text-emerald-600" />
                <span>Rujukan Regulasi (PADG No. 23/2024 & PBI No. 6/2024)</span>
              </div>
              <p className="text-slate-600 leading-relaxed">
                {drillDown.paramDetail}
              </p>
            </div>

            {/* 4. Detailed Breakdown of Metrics (Numerator & Denominator) */}
            {drillDown.metricDetail && (
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs space-y-3">
                <h4 className="font-semibold text-xs text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
                  <Activity className="w-4 h-4 text-emerald-600" />
                  Rincian Komponen Pembentuk Angka
                </h4>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  {drillDown.metricDetail.valid_days !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Hari Kerja Valid:</span>
                      <strong className="text-slate-800 text-sm">
                        {drillDown.metricDetail.valid_days} / {drillDown.metricDetail.total_days || 60} Hari Kerja
                      </strong>
                    </div>
                  )}

                  {drillDown.metricDetail.line_du !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Counterparty Line DU:</span>
                      <strong className="text-slate-800 text-sm">
                        {drillDown.metricDetail.line_du} Bank DU (Target: {drillDown.metricDetail.target_du || 10})
                      </strong>
                    </div>
                  )}

                  {drillDown.metricDetail.line_non_du !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Counterparty Line Non-DU:</span>
                      <strong className="text-slate-800 text-sm">
                        {drillDown.metricDetail.line_non_du} Bank Non-DU (Target: {drillDown.metricDetail.target_non_du || 10})
                      </strong>
                    </div>
                  )}

                  {drillDown.metricDetail.win_perdana !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Volume Win Perdana:</span>
                      <strong className="text-slate-800 text-sm">
                        Rp {drillDown.metricDetail.win_perdana.toLocaleString()} Miliar
                      </strong>
                    </div>
                  )}

                  {drillDown.metricDetail.actual_sales !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Penjualan Sekunder:</span>
                      <strong className="text-slate-800 text-sm">
                        Rp {drillDown.metricDetail.actual_sales.toLocaleString()} M (Target 30%: Rp {drillDown.metricDetail.target_sales?.toLocaleString()} M)
                      </strong>
                    </div>
                  )}

                  {drillDown.metricDetail.valid_sessions !== undefined && (
                    <div className="p-2.5 bg-slate-50 rounded-lg">
                      <span className="text-slate-500 block">Sesi Matchmaking Hadir:</span>
                      <strong className="text-slate-800 text-sm">
                        {drillDown.metricDetail.valid_sessions} / {drillDown.metricDetail.total_sessions || 12} Sesi
                      </strong>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 5. Daftar Transaksi / Kuotasi yang Gugur (FAILED ITEMS TABLE) */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-semibold text-xs text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
                  <TrendingDown className="w-4 h-4 text-rose-600" />
                  Daftar Transaksi / Kuotasi Gugur ({failedItems.length})
                </h4>
                {failedItems.length > 0 && (
                  <span className="text-[11px] font-medium text-rose-600 bg-rose-50 px-2 py-0.5 rounded border border-rose-200">
                    Tidak memenuhi kriteria PADG No. 23/2024
                  </span>
                )}
              </div>

              {failedItems.length > 0 ? (
                <div className="border border-slate-200 rounded-xl overflow-hidden shadow-xs">
                  <div className="max-h-64 overflow-y-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead className="bg-slate-100 text-slate-700 sticky top-0 border-b border-slate-200 font-semibold">
                        <tr>
                          <th className="p-2.5">Tanggal / ID</th>
                          <th className="p-2.5">Tenor / Seri</th>
                          <th className="p-2.5">Nilai Realisasi</th>
                          <th className="p-2.5">Batas Aturan</th>
                          <th className="p-2.5">Keterangan Diskualifikasi</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {failedItems.map((item, idx) => {
                          const idOrDate = item.deal_id || item.tanggal || `Item #${idx + 1}`
                          const tenorOrSeri = item.tenor || item.seri || item.parameter || "-"
                          const actualVal =
                            item.spread_bps !== undefined
                              ? `${item.spread_bps} bps`
                              : item.tenor_hari !== undefined
                              ? `${item.tenor_hari} hari`
                              : item.realisasi_penjualan_sekunder !== undefined
                              ? `Rp ${item.realisasi_penjualan_sekunder} M`
                              : item.realisasi_line_du !== undefined
                              ? `DU: ${item.realisasi_line_du}, Non: ${item.realisasi_line_non_du}`
                              : "-"

                          const limitVal =
                            item.max_allowed_bps !== undefined
                              ? `Maks ${item.max_allowed_bps} bps`
                              : item.min_allowed_tenor !== undefined
                              ? `Min ${item.min_allowed_tenor} hari`
                              : item.target_kewajiban_30pct !== undefined
                              ? `Min Rp ${item.target_kewajiban_30pct} M`
                              : item.target_line_du !== undefined
                              ? `Min 10 DU & 10 Non-DU`
                              : "-"

                          return (
                            <tr key={idx} className="hover:bg-rose-50/40 transition-colors">
                              <td className="p-2.5 font-mono text-[11px] text-slate-800 font-semibold whitespace-nowrap">
                                {idOrDate}
                              </td>
                              <td className="p-2.5 text-slate-600 whitespace-nowrap">
                                {tenorOrSeri}
                              </td>
                              <td className="p-2.5 font-bold text-rose-700 whitespace-nowrap">
                                {actualVal}
                              </td>
                              <td className="p-2.5 text-slate-600 whitespace-nowrap">
                                {limitVal}
                              </td>
                              <td className="p-2.5 text-rose-700 text-[11px] leading-tight">
                                {item.alasan || "Melanggar batas parameter"}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="p-5 text-center bg-slate-50 rounded-xl border border-slate-200 text-xs text-slate-500 flex flex-col items-center">
                  <CheckCircle className="w-6 h-6 text-emerald-600 mb-1" />
                  <span className="font-semibold text-slate-700">Tidak Ada Transaksi Gugur</span>
                  <span className="text-[11px] text-slate-400 mt-0.5">
                    Seluruh kuotasi dan transaksi bank memenuhi kriteria validasi PADG No. 23/2024.
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Drawer Footer Actions */}
          <div className="p-5 bg-slate-50 border-t border-slate-200 flex items-center justify-between gap-3">
            <a
              href={`/api/export/worksheet/${drillDown.bankId}`}
              download
              className="flex items-center space-x-1.5 px-4 py-2 bg-white hover:bg-slate-100 text-slate-800 rounded-lg border border-slate-300 text-xs font-semibold shadow-xs transition-colors"
            >
              <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
              <span>Unduh Lembar Kerja (.xlsx)</span>
            </a>

            <div className="flex items-center space-x-2">
              <button
                onClick={() => {
                  closeDrillDown()
                  setActiveMenu("reconciliation")
                }}
                className="flex items-center space-x-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors"
              >
                <span>Buka di Reconciliation Center</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
