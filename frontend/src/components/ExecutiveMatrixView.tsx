"use client"

import React, { useState, useMemo } from "react"
import { useApp } from "@/context/AppContext"
import { BankScoreMatrixItem, ThresholdStage } from "@/types"
import {
  Building2,
  ShieldCheck,
  AlertTriangle,
  FileSpreadsheet,
  Search,
  Filter,
  TrendingUp,
  Download,
  Info,
  CheckCircle,
  XCircle,
  HelpCircle,
  Layers,
  ArrowUpDown,
} from "lucide-react"

// Definisi Parameter PUVA
const PUVA_PARAMS = [
  { code: "B1", name: "Repo Quotes", full: "Kuotasi Harga Repo", weight: 2.5, detail: "Setiap hari kerja; spread maks. 5 bps (O/N) & 20 bps (1W, 1M)" },
  { code: "B2", name: "SRBI Quotes", full: "Kuotasi Harga SRBI", weight: 2.5, detail: "Setiap hari kerja; seri SRBI tradable; spread maks. 20 bps" },
  { code: "B3", name: "OIS Quotes", full: "Kuotasi Harga OIS", weight: 2.5, detail: "Setiap hari kerja; tenor 1M & 3M; spread maks. 20 bps" },
  { code: "B4", name: "Repo Line", full: "Counterparty Line Repo", weight: 7.5, detail: "Minimal 10 bank DU dan 10 bank non-DU pada akhir periode" },
  { code: "B5", name: "OIS Line", full: "Counterparty Line OIS", weight: 2.5, detail: "Minimal 10 bank DU pada akhir periode" },
  { code: "B6", name: "SRBI Sekunder", full: "Penjualan SRBI Pasar Sekunder", weight: 7.5, detail: "Minimal 30% dari volume win pada lelang pasar perdana (status SETTLED)" },
  { code: "B7a", name: "Repo Sekunder", full: "Transaksi Repo Pasar Sekunder", weight: 20.0, detail: "Tenor minimal 2 minggu (>=14 hari), minimal 60% hari kerja (36 hari)" },
  { code: "B7b", name: "SRBI Tenor 3B", full: "Transaksi SRBI Pasar Sekunder", weight: 5.0, detail: "Sisa jangka waktu minimal 3 bulan, minimal 60% hari kerja (36 hari)" },
  { code: "B8", name: "OIS Match", full: "Matchmaking OIS", weight: 10.0, detail: "Tenor 1M dan 3M pada setiap sesi matchmaking OIS (6 periode)" },
]

const THRESHOLD_VALS: Record<ThresholdStage, Record<string, number>> = {
  EARLY: { B1: 80, B2: 80, B3: 80, B4: 50, B5: 50, B6: 80, B7a: 80, B7b: 80, B8: 80 },
  INTERMEDIATE: { B1: 85, B2: 85, B3: 85, B4: 70, B5: 70, B6: 85, B7a: 85, B7b: 85, B8: 85 },
  END_STATE: { B1: 90, B2: 90, B3: 90, B4: 80, B5: 80, B6: 90, B7a: 90, B7b: 90, B8: 90 },
}

export const ExecutiveMatrixView: React.FC = () => {
  const {
    matrix,
    selectedStage,
    isMasked,
    findings,
    openDrillDown,
    isLoading,
  } = useApp()

  const [searchQuery, setSearchQuery] = useState("")
  const [selectedKbmi, setSelectedKbmi] = useState("ALL")
  const [selectedStatus, setSelectedStatus] = useState("ALL")
  const [sortField, setSortField] = useState<string>("bank_id")
  const [sortAsc, setSortAsc] = useState<boolean>(true)

  // 1. KPI Calculations
  const totalBanks = matrix.length
  const fullCompliance = matrix.filter((m) => m.compliance_status === "MEMENUHI").length
  const attentionCount = totalBanks - fullCompliance

  const puvaScores = matrix.map((m) => m.total_puva_score || 0)
  const averagePuva = puvaScores.length > 0 ? (puvaScores.reduce((a, b) => a + b, 0) / puvaScores.length).toFixed(1) : "0"
  
  // Median calculation
  const sortedPuva = [...puvaScores].sort((a, b) => a - b)
  const medianPuva = sortedPuva.length > 0
    ? (sortedPuva.length % 2 === 0
        ? ((sortedPuva[sortedPuva.length / 2 - 1] + sortedPuva[sortedPuva.length / 2]) / 2).toFixed(1)
        : sortedPuva[Math.floor(sortedPuva.length / 2)].toFixed(1))
    : "0"

  // 2. Filter & Sort Matrix
  const filteredMatrix = useMemo(() => {
    return matrix
      .filter((m) => {
        const query = searchQuery.toLowerCase()
        const matchesQuery =
          m.bank_id.toLowerCase().includes(query) ||
          m.masked_alias.toLowerCase().includes(query) ||
          m.nama_resmi_bank.toLowerCase().includes(query)

        const matchesKbmi = selectedKbmi === "ALL" || m.kelompok_kbmi === selectedKbmi
        const matchesStatus = selectedStatus === "ALL" || m.compliance_status === selectedStatus

        return matchesQuery && matchesKbmi && matchesStatus
      })
      .sort((a, b) => {
        let valA: any = a[sortField as keyof BankScoreMatrixItem]
        let valB: any = b[sortField as keyof BankScoreMatrixItem]

        if (sortField === "composite_score" || sortField === "total_puva_score") {
          valA = Number(valA || 0)
          valB = Number(valB || 0)
        } else {
          valA = String(valA || "")
          valB = String(valB || "")
        }

        if (valA < valB) return sortAsc ? -1 : 1
        if (valA > valB) return sortAsc ? 1 : -1
        return 0
      })
  }, [matrix, searchQuery, selectedKbmi, selectedStatus, sortField, sortAsc])

  const handleCellClick = (item: BankScoreMatrixItem, paramCode: string) => {
    const rawRate = item.raw_metrics[paramCode] || 0
    const isPassed = item.passed_flags[paramCode] || false
    const score = item.weighted_scores[paramCode] || 0
    const paramDef = PUVA_PARAMS.find((p) => p.code === paramCode)
    const weight = paramDef ? paramDef.weight : 0
    const threshold = THRESHOLD_VALS[selectedStage]?.[paramCode] || 80

    // Cari tiket temuan dan rincian transaksi gugur jika ada
    const ticket = findings.find(
      (f) => f.bank_id === item.bank_id && f.parameter_code.toUpperCase() === paramCode.toUpperCase()
    )

    const failedTx = ticket ? ticket.detail_transaksi_gugur : []

    openDrillDown({
      bankId: item.bank_id,
      bankAlias: item.masked_alias,
      bankOfficialName: item.nama_resmi_bank,
      kbmi: item.kelompok_kbmi,
      paramCode,
      paramName: paramDef ? paramDef.full : paramCode,
      paramDetail: paramDef ? paramDef.detail : "",
      rawRate,
      isPassed,
      score,
      weight,
      threshold,
      stage: selectedStage,
      metricDetail: item.detail_metrics?.[paramCode],
      failedTransactions: failedTx,
      findingId: ticket?.finding_id,
    })
  }

  return (
    <div className="space-y-6">
      
      {/* 1. Header Overview */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            Executive Matrix Kepatuhan DU PUVA
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">
              PADG No. 23/2024
            </span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Monitoring Pemenuhan 9 Indikator Pasar Uang & Valas 21 Dealer Utama Bank Indonesia Triwulan II 2026.
          </p>
        </div>

        <div className="flex items-center space-x-2 text-xs">
          <span className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg shadow-2xs font-medium text-slate-600">
            Ambang Batas Aktif: <strong className="text-emerald-700">{selectedStage} STATE</strong>
          </span>
          <span className="px-3 py-1.5 bg-slate-100 border border-slate-200 rounded-lg text-slate-500 font-mono">
            {matrix.length} Records
          </span>
        </div>
      </div>

      {/* 2. 4 KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Bank DU */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs flex items-start justify-between">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Total Dealer Utama
            </span>
            <div className="text-2xl font-black text-slate-900 mt-1">21 Bank</div>
            <div className="text-[11px] text-slate-500 mt-1.5 flex items-center space-x-1">
              <span className="font-semibold text-slate-700">4</span> KBMI 4 ·{" "}
              <span className="font-semibold text-slate-700">10</span> KBMI 3 ·{" "}
              <span className="font-semibold text-slate-700">7</span> KBMI 2
            </div>
          </div>
          <div className="p-2.5 bg-slate-100 text-slate-600 rounded-xl">
            <Building2 className="w-5 h-5" />
          </div>
        </div>

        {/* Card 2: Lolos Seluruh Threshold (100%) */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs flex items-start justify-between">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Lolos Seluruh Threshold
            </span>
            <div className="text-2xl font-black text-emerald-600 mt-1">
              {fullCompliance} Bank
            </div>
            <div className="text-[11px] text-emerald-700 mt-1.5 flex items-center space-x-1 font-medium">
              <CheckCircle className="w-3.5 h-3.5" />
              <span>Capaian PUVA Penuh (60/60 Poin)</span>
            </div>
          </div>
          <div className="p-2.5 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-200">
            <ShieldCheck className="w-5 h-5" />
          </div>
        </div>

        {/* Card 3: Perlu Klarifikasi / Perhatian */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs flex items-start justify-between">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Perlu Klarifikasi / Temuan
            </span>
            <div className="text-2xl font-black text-rose-600 mt-1">
              {attentionCount} Bank
            </div>
            <div className="text-[11px] text-slate-500 mt-1.5">
              <span className="text-amber-600 font-semibold">4</span> Pembinaan DSMM ·{" "}
              <span className="text-rose-600 font-semibold">1</span> Teguran Tertulis
            </div>
          </div>
          <div className="p-2.5 bg-rose-50 text-rose-600 rounded-xl border border-rose-200">
            <AlertTriangle className="w-5 h-5" />
          </div>
        </div>

        {/* Card 4: Rata-rata & Median PUVA Score */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs flex items-start justify-between">
          <div>
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Rerata & Median Skor PUVA
            </span>
            <div className="text-2xl font-black text-slate-900 mt-1 flex items-baseline gap-1.5">
              <span>{averagePuva}%</span>
              <span className="text-xs font-normal text-slate-400">/ 60%</span>
            </div>
            <div className="text-[11px] text-slate-500 mt-1.5">
              Nilai Median: <strong className="text-slate-700">{medianPuva}%</strong> (Maks. 60%)
            </div>
          </div>
          <div className="p-2.5 bg-blue-50 text-blue-600 rounded-xl border border-blue-200">
            <TrendingUp className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* 3. Filter & Search Toolbar */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 flex-1 min-w-[280px]">
          {/* Search Input */}
          <div className="relative flex-1 max-w-sm">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Cari Bank ID, Alias (Bank A), atau Nama Bank..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:bg-white transition-all"
            />
          </div>

          {/* Filter KBMI */}
          <div className="flex items-center text-xs">
            <span className="text-slate-400 mr-2 text-[11px] font-medium">KBMI:</span>
            <select
              value={selectedKbmi}
              onChange={(e) => setSelectedKbmi(e.target.value)}
              className="bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 focus:outline-none cursor-pointer"
            >
              <option value="ALL">Semua KBMI (21)</option>
              <option value="KBMI 4">KBMI 4 (4 Bank)</option>
              <option value="KBMI 3">KBMI 3 (10 Bank)</option>
              <option value="KBMI 2">KBMI 2 (7 Bank)</option>
            </select>
          </div>

          {/* Filter Status */}
          <div className="flex items-center text-xs">
            <span className="text-slate-400 mr-2 text-[11px] font-medium">Status:</span>
            <select
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
              className="bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 focus:outline-none cursor-pointer"
            >
              <option value="ALL">Semua Status</option>
              <option value="MEMENUHI">Lolos Penuh (100%)</option>
              <option value="PEMBINAAN_DSMM">Pembinaan DSMM (90-99%)</option>
              <option value="SANKSI_TEGURAN">Sanksi Teguran (&lt;90%)</option>
            </select>
          </div>
        </div>

        {/* Legend / Guidance Tip */}
        <div className="flex items-center space-x-3 text-xs text-slate-500">
          <div className="flex items-center space-x-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
            <span className="text-[11px]">Memenuhi Threshold</span>
          </div>
          <div className="flex items-center space-x-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
            <span className="text-[11px]">Di Bawah Threshold (Klik Sel)</span>
          </div>
        </div>
      </div>

      {/* 4. Interactive Matrix Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            {/* Table Header */}
            <thead>
              <tr className="bg-[#0F172A] text-white">
                <th className="p-3 font-semibold text-[11px] text-center w-12 sticky left-0 z-10 bg-[#0F172A]">
                  No
                </th>
                <th className="p-3 font-semibold text-[11px] w-48 sticky left-12 z-10 bg-[#0F172A] border-r border-slate-800">
                  Dealer Utama (Bank)
                </th>
                <th className="p-3 font-semibold text-[11px] text-center w-16">
                  KBMI
                </th>
                {PUVA_PARAMS.map((p) => {
                  const th = THRESHOLD_VALS[selectedStage]?.[p.code] || 80
                  return (
                    <th
                      key={p.code}
                      className="p-2.5 text-center font-semibold text-[11px] min-w-[76px] border-l border-slate-800"
                      title={`${p.code}: ${p.full} (Bobot ${p.weight}% | Min ${th}%)`}
                    >
                      <div className="font-bold text-white">{p.code}</div>
                      <div className="text-[9px] text-emerald-400 font-mono font-normal">
                        {p.weight}%
                      </div>
                    </th>
                  )
                })}
                <th className="p-3 font-bold text-[11px] text-center min-w-[90px] border-l border-slate-800 bg-slate-900 text-emerald-400">
                  Subtotal PUVA (60%)
                </th>
                <th className="p-3 font-bold text-[11px] text-center min-w-[95px] border-l border-slate-800 bg-slate-900 text-white">
                  Komposit (100%)
                </th>
                <th className="p-3 font-semibold text-[11px] text-center min-w-[130px] border-l border-slate-800">
                  Tindak Lanjut BI
                </th>
                <th className="p-3 font-semibold text-[11px] text-center w-16 border-l border-slate-800">
                  Aksi
                </th>
              </tr>
            </thead>

            {/* Table Body */}
            <tbody className="divide-y divide-slate-100">
              {filteredMatrix.map((item, idx) => {
                const displayName = isMasked ? item.masked_alias : item.nama_resmi_bank
                const isAllPass = item.compliance_status === "MEMENUHI"
                const isWarning = item.compliance_status === "PEMBINAAN_DSMM"
                const isSevere = item.compliance_status === "SANKSI_TEGURAN"

                return (
                  <tr
                    key={item.bank_id}
                    className={`hover:bg-slate-50/80 transition-colors ${
                      isSevere ? "bg-rose-50/30" : isWarning ? "bg-amber-50/20" : ""
                    }`}
                  >
                    {/* Column: No */}
                    <td className="p-3 text-center text-slate-400 font-mono text-[11px] sticky left-0 bg-white">
                      {idx + 1}
                    </td>

                    {/* Column: Bank Name & ID */}
                    <td className="p-3 font-medium text-slate-900 sticky left-12 bg-white border-r border-slate-200">
                      <div className="flex flex-col">
                        <span className="font-bold text-xs text-slate-800 truncate" title={displayName}>
                          {displayName}
                        </span>
                        <div className="flex items-center space-x-1.5 text-[10px] text-slate-400 mt-0.5">
                          <span className="font-mono">{item.bank_id}</span>
                          <span>·</span>
                          <span>{item.masked_alias}</span>
                        </div>
                      </div>
                    </td>

                    {/* Column: KBMI */}
                    <td className="p-3 text-center">
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">
                        {item.kelompok_kbmi}
                      </span>
                    </td>

                    {/* 9 PUVA Parameter Cells */}
                    {PUVA_PARAMS.map((p) => {
                      const raw = item.raw_metrics[p.code] ?? 0
                      const passed = item.passed_flags[p.code] ?? false
                      const score = item.weighted_scores[p.code] ?? 0

                      return (
                        <td
                          key={p.code}
                          className="p-1.5 text-center border-l border-slate-100"
                        >
                          <button
                            onClick={() => handleCellClick(item, p.code)}
                            title={`Klik untuk rincian ${p.code}: ${p.full}\nRealisasi: ${raw}%\nSkor: ${score} / ${p.weight}%`}
                            className={`w-full py-1.5 px-1 rounded-lg border text-center transition-all duration-150 group cursor-pointer focus:outline-none focus:ring-2 focus:ring-emerald-500/50 ${
                              passed
                                ? "bg-emerald-50/70 border-emerald-200/80 text-emerald-800 hover:bg-emerald-100 hover:border-emerald-300"
                                : "bg-rose-50 border-rose-300 text-rose-800 font-bold hover:bg-rose-100 hover:border-rose-400 shadow-xs"
                            }`}
                          >
                            <div className="text-[11px] font-bold leading-none">
                              {raw.toFixed(1)}%
                            </div>
                            <div
                              className={`text-[9px] mt-0.5 font-mono ${
                                passed ? "text-emerald-600" : "text-rose-600 font-bold"
                              }`}
                            >
                              {score.toFixed(1)}p
                            </div>
                          </button>
                        </td>
                      )
                    })}

                    {/* Subtotal PUVA (Maks 60%) */}
                    <td className="p-2.5 text-center border-l border-slate-200 bg-slate-50/50">
                      <div className="font-extrabold text-xs text-slate-900 font-mono">
                        {item.total_puva_score.toFixed(1)}%
                      </div>
                      <div className="w-14 bg-slate-200 rounded-full h-1.5 mx-auto mt-1 overflow-hidden">
                        <div
                          className="bg-emerald-600 h-1.5 rounded-full"
                          style={{ width: `${(item.total_puva_score / 60) * 100}%` }}
                        />
                      </div>
                    </td>

                    {/* Komposit (100%) */}
                    <td className="p-2.5 text-center border-l border-slate-200 bg-slate-50/50">
                      <div className="font-extrabold text-xs text-slate-900 font-mono">
                        {item.composite_score.toFixed(1)}%
                      </div>
                      <span className="text-[9px] text-slate-400">OM: +40%</span>
                    </td>

                    {/* Status & Tindak Lanjut BI */}
                    <td className="p-2.5 text-center border-l border-slate-200">
                      {isAllPass && (
                        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                          Memenuhi Penuh
                        </span>
                      )}
                      {isWarning && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">
                          Pembinaan DSMM
                        </span>
                      )}
                      {isSevere && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300">
                          Sanksi Teguran
                        </span>
                      )}
                    </td>

                    {/* Export Action */}
                    <td className="p-2 text-center border-l border-slate-200">
                      <a
                        href={`/api/export/worksheet/${item.bank_id}`}
                        download
                        title={`Unduh Worksheet Excel (${item.masked_alias})`}
                        className="inline-flex p-1.5 text-slate-500 hover:text-emerald-700 hover:bg-emerald-50 rounded-lg border border-transparent hover:border-emerald-200 transition-colors"
                      >
                        <FileSpreadsheet className="w-4 h-4" />
                      </a>
                    </td>
                  </tr>
                )
              })}

              {filteredMatrix.length === 0 && (
                <tr>
                  <td colSpan={15} className="p-8 text-center text-slate-500 text-xs">
                    Tidak ada bank yang cocok dengan filter pencarian "{searchQuery}".
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Table Footer Instructions */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 flex flex-wrap items-center justify-between text-[11px] text-slate-500">
          <div className="flex items-center space-x-1.5">
            <Info className="w-3.5 h-3.5 text-emerald-600" />
            <span>
              <strong>Tip Interaktif:</strong> Klik pada sel persentase mana pun (misal: <strong>76.7%</strong> pada Bank A atau <strong>72.2%</strong> pada Bank R) untuk membuka Drawer rincian data transaksi harian yang gugur.
            </span>
          </div>
          <div>
            Menampilkan {filteredMatrix.length} dari 21 Bank Dealer Utama
          </div>
        </div>
      </div>
    </div>
  )
}
