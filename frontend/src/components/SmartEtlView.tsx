"use client"

import React, { useState } from "react"
import { useApp } from "@/context/AppContext"
import {
  Database,
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Layers,
  ArrowRight,
  ShieldCheck,
  FileText,
} from "lucide-react"

export const SmartEtlView: React.FC = () => {
  const { banks, refreshData, selectedStage } = useApp()
  const [isProcessing, setIsProcessing] = useState(false)
  const [etlResult, setEtlResult] = useState<any>(null)

  const handleRunSampleEtl = async () => {
    setIsProcessing(true)
    try {
      const formData = new FormData()
      formData.append("use_sample_datasets", "true")
      formData.append("stage", selectedStage)

      const res = await fetch("/api/etl/upload", {
        method: "POST",
        body: formData,
      })
      if (res.ok) {
        const data = await res.json()
        setEtlResult(data)
        await refreshData()
      }
    } catch (err) {
      console.error("Gagal menjalankan ETL:", err)
    } finally {
      setIsProcessing(false)
    }
  }

  const feeders = [
    {
      id: "bloomberg_sppa",
      name: "Bloomberg & SPPA Kuotasi",
      code: "01_Raw_Kuotasi_Bloomberg_SPPA.xlsx",
      desc: "Kuotasi Harian Repo (SPPA), SRBI & OIS (Bloomberg)",
      status: "TERVERIFIKASI",
      records: "7.560 Baris Data",
      indicators: "B1, B2, B3",
    },
    {
      id: "survey",
      name: "Survey Counterparty Line",
      code: "02_Raw_Survey_Counterparty_Line.xlsx",
      desc: "Cut-off Fasilitas Line Repo & OIS per Akhir Triwulan",
      status: "TERVERIFIKASI",
      records: "21 Laporan Bank",
      indicators: "B4, B5",
    },
    {
      id: "hartis",
      name: "HARTIS Transaksi Lelang & Sekunder",
      code: "03_Raw_HARTIS_Transaksi.xlsx",
      desc: "Lelang Perdana SRBI & Transaksi Sekunder Repo/SRBI",
      status: "TERVERIFIKASI",
      records: "2.154 Transaksi Settled",
      indicators: "B6, B7a, B7b",
    },
    {
      id: "antasena",
      name: "DS Antasena Matchmaking OIS",
      code: "04_Raw_DS_Antasena_Matchmaking_OIS.xlsx",
      desc: "Log Partisipasi Kuotasi 6 Periode Matchmaking",
      status: "TERVERIFIKASI",
      records: "252 Sesi Kuotasi",
      indicators: "B8",
    },
    {
      id: "sanggahan",
      name: "Simulasi Sanggahan & Bukti Bank",
      code: "05_Simulasi_Sanggahan_Bank_DU.xlsx",
      desc: "5 Tiket Sanggahan Bank DU untuk Uji Coba AI & Verifikasi",
      status: "TERSEDIA",
      records: "5 Tiket Temuan",
      indicators: "Resolution Center",
    },
  ]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            Smart Multi-Source ETL & Entity Resolution
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">
              Pipeline Otomatis
            </span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Integrasi 5 sumber data mentah, normalisasi ticker & sandi, serta kalkulasi otomatis 9 indikator PUVA.
          </p>
        </div>

        <button
          onClick={handleRunSampleEtl}
          disabled={isProcessing}
          className="flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
        >
          {isProcessing ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Memproses Pipeline ETL...</span>
            </>
          ) : (
            <>
              <Database className="w-4 h-4" />
              <span>Jalankan Ulang Pipeline ETL (Demo)</span>
            </>
          )}
        </button>
      </div>

      {/* Result Notification if triggered */}
      {etlResult && (
        <div className="bg-emerald-50 border border-emerald-300 rounded-xl p-4 text-emerald-950 text-xs shadow-xs animate-in fade-in duration-200">
          <div className="flex items-center space-x-2 font-bold mb-2 text-sm text-emerald-800">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span>{etlResult.message}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-slate-700 bg-white/70 p-3 rounded-lg border border-emerald-200">
            <div>
              <span className="text-slate-500 block">Kuotasi Diproses:</span>
              <strong>{etlResult.processed_rows?.quotes_bloomberg_sppa} baris</strong>
            </div>
            <div>
              <span className="text-slate-500 block">Transaksi Sekunder:</span>
              <strong>{etlResult.processed_rows?.hartis_secondary} deal</strong>
            </div>
            <div>
              <span className="text-slate-500 block">Bank Lolos Penuh:</span>
              <strong className="text-emerald-700">{etlResult.evaluation_summary?.full_compliance_count} Bank</strong>
            </div>
            <div>
              <span className="text-slate-500 block">Temuan Terdeteksi:</span>
              <strong className="text-rose-700">{etlResult.sample_disputes_verified} Tiket</strong>
            </div>
          </div>
        </div>
      )}

      {/* 5 Feeders Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {feeders.map((f) => (
          <div
            key={f.id}
            className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs flex flex-col justify-between space-y-3"
          >
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                  {f.status}
                </span>
                <span className="text-[10px] font-semibold text-slate-400 font-mono">
                  {f.indicators}
                </span>
              </div>
              <h3 className="font-bold text-sm text-slate-900">{f.name}</h3>
              <p className="text-xs text-slate-500 mt-1">{f.desc}</p>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-600">
              <span className="font-mono text-[11px] text-slate-400 truncate max-w-[160px]" title={f.code}>
                {f.code}
              </span>
              <strong className="text-slate-800 text-[11px]">{f.records}</strong>
            </div>
          </div>
        ))}

        {/* Dropzone Placeholder for Live Manual Upload */}
        <div className="bg-slate-50/70 border-2 border-dashed border-slate-300 rounded-xl p-5 flex flex-col items-center justify-center text-center space-y-2 hover:bg-slate-100/70 transition-colors cursor-pointer">
          <UploadCloud className="w-8 h-8 text-slate-400" />
          <div className="font-semibold text-xs text-slate-700">Unggah File Baru (.xlsx / .csv)</div>
          <p className="text-[10px] text-slate-400 max-w-[200px]">
            Tarik & lepaskan file mentah baru dari Bloomberg atau SPPA untuk pengolahan instan.
          </p>
        </div>
      </div>

      {/* Entity Resolution Reference Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <h3 className="font-bold text-xs text-slate-800 uppercase tracking-wider">
              Tabel Master Entity Resolution (21 Bank Dealer Utama)
            </h3>
          </div>
          <span className="text-[11px] text-slate-500">
            Pemetaan otomatis 3 sandi berbeda ke 1 Bank_ID tunggal
          </span>
        </div>

        <div className="overflow-x-auto max-h-72">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-100 text-slate-700 font-semibold sticky top-0 border-b border-slate-200">
              <tr>
                <th className="p-2.5 w-20">Bank ID</th>
                <th className="p-2.5 w-28">Masked Alias</th>
                <th className="p-2.5">Nama Resmi Bank (PT Bank ...)</th>
                <th className="p-2.5 w-24">Kelompok</th>
                <th className="p-2.5 w-32 font-mono">Ticker Bloomberg</th>
                <th className="p-2.5 w-32 font-mono">Sandi SPPA/Antasena</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium">
              {banks.map((b) => (
                <tr key={b.bank_id} className="hover:bg-slate-50 transition-colors">
                  <td className="p-2.5 font-bold font-mono text-emerald-700">{b.bank_id}</td>
                  <td className="p-2.5 font-semibold text-slate-800">{b.masked_alias}</td>
                  <td className="p-2.5 text-slate-700">{b.nama_resmi_bank}</td>
                  <td className="p-2.5 text-slate-500">{b.kelompok_kbmi}</td>
                  <td className="p-2.5 font-mono text-[11px] text-blue-600 bg-blue-50/40">{b.kode_bloomberg}</td>
                  <td className="p-2.5 font-mono text-[11px] text-amber-700 bg-amber-50/40">{b.kode_sppa_antasena}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
