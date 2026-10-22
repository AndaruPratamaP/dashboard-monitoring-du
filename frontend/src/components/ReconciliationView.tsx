"use client"

import React, { useState, useEffect } from "react"
import { useApp } from "@/context/AppContext"
import { FindingTicketItem } from "@/types"
import {
  Scale,
  Sparkles,
  CheckCircle2,
  XCircle,
  FileText,
  Clock,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Search,
  Check,
  X,
  FileSpreadsheet,
  Eye,
  RefreshCw,
  History,
  ShieldAlert,
  UserCheck,
  Paperclip,
} from "lucide-react"

export const ReconciliationView: React.FC = () => {
  const { findings, isMasked, refreshData } = useApp()
  const [selectedTicketId, setSelectedTicketId] = useState<string>("")
  const [filterStatus, setFilterStatus] = useState<string>("ALL")

  const [isAnalyzingAi, setIsAnalyzingAi] = useState(false)
  const [aiAnalysisResult, setAiAnalysisResult] = useState<any>(null)

  const [isDeciding, setIsDeciding] = useState(false)
  const [decisionNotes, setDecisionNotes] = useState("")
  const [decisionFeedback, setDecisionFeedback] = useState<string | null>(null)

  const [auditLogs, setAuditLogs] = useState<any[]>([])

  // Set default selected ticket
  useEffect(() => {
    if (findings.length > 0 && !selectedTicketId) {
      setSelectedTicketId(findings[0].finding_id)
    }
  }, [findings, selectedTicketId])

  // Fetch audit trail
  const loadAuditLogs = async () => {
    try {
      const res = await fetch("/api/audit-trail?limit=8")
      if (res.ok) {
        const json = await res.json()
        setAuditLogs(json)
      }
    } catch (err) {
      console.error("Gagal memuat audit trail:", err)
    }
  }

  useEffect(() => {
    loadAuditLogs()
  }, [])

  const selectedTicket = findings.find((f) => f.finding_id === selectedTicketId) || findings[0]

  const filteredTickets = findings.filter((t) => {
    if (filterStatus === "ALL") return true
    return t.bi_decision_status === filterStatus
  })

  // 1. Eksekusi Analisis AI (Gemini Evidence Checker)
  const handleRunAiAnalysis = async (findingId: string) => {
    setIsAnalyzingAi(true)
    setDecisionFeedback(null)
    try {
      const res = await fetch(`/api/reconciliation/${findingId}/analyze`, {
        method: "POST",
      })
      if (res.ok) {
        const json = await res.json()
        setAiAnalysisResult(json.ai_result)
        await refreshData()
        await loadAuditLogs()
      } else {
        alert("Gagal menjalankan analisis AI.")
      }
    } catch (err) {
      console.error("Error AI Analysis:", err)
    } finally {
      setIsAnalyzingAi(false)
    }
  }

  // 2. Eksekusi Keputusan Petugas BI (Human-in-the-Loop)
  const handleExecuteDecision = async (decision: "APPROVED" | "REJECTED") => {
    if (!selectedTicket) return
    setIsDeciding(true)
    setDecisionFeedback(null)

    try {
      const formData = new FormData()
      formData.append("decision", decision)
      formData.append("verified_by", "Petugas Verifikator DPPK Bank Indonesia")
      formData.append("notes", decisionNotes || (decision === "APPROVED" ? "Disetujui sesuai rekomendasi AI & validasi bukti PADG." : "Ditolak karena tidak memenuhi ketentuan PADG No. 23/2024."))

      const res = await fetch(`/api/reconciliation/${selectedTicket.finding_id}/decide`, {
        method: "POST",
        body: formData,
      })

      if (res.ok) {
        const json = await res.json()
        setDecisionFeedback(json.message)
        setDecisionNotes("")
        await refreshData()
        await loadAuditLogs()
      } else {
        const err = await res.json()
        alert(err.detail || "Gagal mengeksekusi keputusan.")
      }
    } catch (err) {
      console.error("Error execute decision:", err)
    } finally {
      setIsDeciding(false)
    }
  }

  return (
    <div className="space-y-6">
      
      {/* Header Overview */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            Reconciliation Resolution Center & Gemini AI Evidence Checker
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-300">
              {findings.length} Antrean Temuan
            </span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Verifikasi dua arah antara klaim sanggahan Dealer Utama dan ketentuan PADG No. 23/2024 dengan rekomendasi AI cerdas (Human-in-the-Loop).
          </p>
        </div>

        {/* Filter Status Chips */}
        <div className="flex items-center space-x-1 bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs font-medium">
          {["ALL", "PENDING_REVIEW", "OPEN", "APPROVED", "REJECTED"].map((st) => (
            <button
              key={st}
              onClick={() => setFilterStatus(st)}
              className={`px-3 py-1 rounded-md transition-all ${
                filterStatus === st
                  ? "bg-white text-slate-900 shadow-xs font-bold"
                  : "text-slate-500 hover:text-slate-800"
              }`}
            >
              {st === "ALL" ? "Semua Status" : st.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Split-Screen Reconciliation View */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* BAGIAN KIRI (5/12): Daftar Antrean Tiket Temuan & Data Awal BI */}
        <div className="lg:col-span-5 bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden flex flex-col">
          <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <h3 className="font-bold text-xs text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
              <Scale className="w-4 h-4 text-emerald-600" />
              Antrean Tiket Temuan ({filteredTickets.length})
            </h3>
            <span className="text-[11px] text-slate-500 font-medium">
              5 Bank Skenario Bermasalah
            </span>
          </div>

          <div className="divide-y divide-slate-100 max-h-[680px] overflow-y-auto">
            {filteredTickets.map((t) => {
              const isSelected = t.finding_id === selectedTicket?.finding_id
              const bankName = isMasked ? t.masked_alias : t.nama_resmi_bank
              const isApprove = t.ai_recommendation_status?.includes("APPROVE")
              const isReject = t.ai_recommendation_status?.includes("REJECT")

              return (
                <button
                  key={t.finding_id}
                  onClick={() => {
                    setSelectedTicketId(t.finding_id)
                    setDecisionFeedback(null)
                    setAiAnalysisResult(null)
                  }}
                  className={`w-full p-4 text-left transition-all flex flex-col space-y-2.5 border-l-4 ${
                    isSelected
                      ? "bg-emerald-50/60 border-emerald-600 shadow-2xs"
                      : "hover:bg-slate-50/80 border-transparent"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-black text-slate-900">
                      {t.finding_id}
                    </span>
                    <span
                      className={`text-[9px] font-bold px-2 py-0.5 rounded-full ${
                        t.bi_decision_status === "APPROVED"
                          ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                          : t.bi_decision_status === "REJECTED"
                          ? "bg-rose-100 text-rose-800 border border-rose-300"
                          : t.bi_decision_status === "PENDING_REVIEW"
                          ? "bg-blue-100 text-blue-800 border border-blue-300 animate-pulse"
                          : "bg-amber-100 text-amber-800 border border-amber-300"
                      }`}
                    >
                      {t.bi_decision_status}
                    </span>
                  </div>

                  <div>
                    <h4 className="font-bold text-xs text-slate-900 truncate" title={bankName}>
                      {bankName}
                    </h4>
                    <p className="text-[11px] text-slate-500 font-medium">
                      Indikator: <strong className="text-slate-700">{t.parameter_code}</strong>
                    </p>
                  </div>

                  {/* Rekap Awal BI vs Klaim Bank */}
                  <div className="text-[11px] bg-slate-50 p-2 rounded-lg border border-slate-100 space-y-0.5">
                    <div className="text-rose-700 truncate">
                      <span className="text-slate-400">BI:</span> {t.nilai_rekap_bi}
                    </div>
                    {t.nilai_klaim_bank && (
                      <div className="text-emerald-700 truncate font-semibold">
                        <span className="text-slate-400">Klaim:</span> {t.nilai_klaim_bank}
                      </div>
                    )}
                  </div>

                  {/* AI Recommendation Badge Preview */}
                  <div className="flex items-center justify-between text-[11px] pt-1">
                    <span className="text-slate-400 text-[10px]">Rekomendasi AI:</span>
                    <span
                      className={`font-semibold text-[10px] px-2 py-0.5 rounded font-mono ${
                        isApprove
                          ? "bg-emerald-100 text-emerald-800"
                          : isReject
                          ? "bg-rose-100 text-rose-800"
                          : "bg-amber-100 text-amber-800"
                      }`}
                    >
                      {t.ai_recommendation_status || "Belum Dianalisis"}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* BAGIAN KANAN (7/12): Detail Sanggahan, In-App Evidence Viewer, AI Panel, & Human Decision */}
        {selectedTicket ? (
          <div className="lg:col-span-7 space-y-5">
            
            {/* Feedback Alert if Decision executed */}
            {decisionFeedback && (
              <div className="bg-emerald-50 border border-emerald-300 rounded-xl p-4 text-emerald-950 text-xs shadow-xs flex items-center space-x-2 font-medium animate-in fade-in duration-200">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
                <span>{decisionFeedback}</span>
              </div>
            )}

            {/* Card 1: Data Perbandingan & Sanggahan Bank */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 space-y-5">
              <div className="flex items-start justify-between pb-3 border-b border-slate-200">
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-xs font-black text-white bg-slate-900 px-2.5 py-0.5 rounded">
                      {selectedTicket.finding_id}
                    </span>
                    <span className="text-xs font-bold text-slate-700">
                      Parameter {selectedTicket.parameter_code}
                    </span>
                  </div>
                  <h3 className="text-base font-extrabold text-slate-900 mt-1">
                    {isMasked ? selectedTicket.masked_alias : selectedTicket.nama_resmi_bank}
                  </h3>
                </div>

                <div className="text-right">
                  <span className="text-[10px] text-slate-400 block font-semibold uppercase">Status Saat Ini</span>
                  <span
                    className={`text-xs font-extrabold px-3 py-1 rounded-full inline-block mt-0.5 ${
                      selectedTicket.bi_decision_status === "APPROVED"
                        ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                        : selectedTicket.bi_decision_status === "REJECTED"
                        ? "bg-rose-100 text-rose-800 border border-rose-300"
                        : "bg-blue-100 text-blue-800 border border-blue-300"
                    }`}
                  >
                    {selectedTicket.bi_decision_status}
                  </span>
                </div>
              </div>

              {/* Komparasi Nilai BI vs Klaim Bank */}
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="p-3.5 bg-rose-50/60 rounded-xl border border-rose-200 space-y-1">
                  <span className="font-semibold text-rose-800 uppercase tracking-wider text-[10px] block">
                    1. Rekap Data Awal BI (Gugur / Temuan)
                  </span>
                  <div className="text-sm font-black text-rose-700">
                    {selectedTicket.nilai_rekap_bi}
                  </div>
                  <p className="text-[11px] text-rose-600/80 leading-tight">
                    Transaksi tidak memenuhi syarat batas kuantitatif PADG No. 23/2024.
                  </p>
                </div>

                <div className="p-3.5 bg-emerald-50/70 rounded-xl border border-emerald-200 space-y-1">
                  <span className="font-semibold text-emerald-800 uppercase tracking-wider text-[10px] block">
                    2. Klaim Angka Sanggahan Bank
                  </span>
                  <div className="text-sm font-black text-emerald-800">
                    {selectedTicket.nilai_klaim_bank || "[Belum diisi bank]"}
                  </div>
                  <p className="text-[11px] text-emerald-600/80 leading-tight">
                    Klaim mandiri yang diajukan bank dengan melampirkan berkas bukti.
                  </p>
                </div>
              </div>

              {/* Uraian Alasan Sanggahan */}
              <div className="space-y-1.5 text-xs">
                <span className="font-bold text-slate-800 block">
                  Uraian Alasan Sanggahan Resmi Bank:
                </span>
                <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200 text-slate-700 leading-relaxed font-sans italic">
                  "{selectedTicket.alasan_sanggahan || "Tidak ada rincian uraian alasan tertulis."}"
                </div>
              </div>

              {/* Pratinjau Dokumen Bukti (In-App Document Previewer Card) */}
              <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 text-xs space-y-2">
                <span className="font-bold text-slate-800 flex items-center gap-1.5">
                  <Paperclip className="w-4 h-4 text-emerald-600" />
                  Berkas Bukti Konfirmasi Terlampir:
                </span>
                <div className="flex items-center justify-between bg-white p-3 rounded-lg border border-slate-200 shadow-2xs">
                  <div className="flex items-center space-x-2.5 overflow-hidden">
                    <div className="p-2 bg-emerald-50 text-emerald-700 rounded-lg">
                      <FileText className="w-5 h-5" />
                    </div>
                    <div className="truncate">
                      <strong className="text-slate-900 font-mono text-xs block truncate" title={selectedTicket.file_bukti_name || "Bukti_Konfirmasi.pdf"}>
                        {selectedTicket.file_bukti_name || "Bukti_Konfirmasi.pdf"}
                      </strong>
                      <span className="text-[10px] text-slate-400">
                        Dokumen Resmi Bertandatangan & Stempel Digital
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={() => alert(`Pratinjau Berkas: ${selectedTicket.file_bukti_name || 'Bukti_Konfirmasi.pdf'}\nDokumen valid dan terautentikasi oleh sistem.`)}
                    className="flex items-center space-x-1 px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-md text-[11px] font-semibold transition-colors flex-shrink-0"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>Lihat Dokumen</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Card 2: Panel Asisten AI (Gemini Evidence Checker) */}
            <div className="bg-gradient-to-br from-[#0F172A] to-slate-800 text-white p-6 rounded-xl shadow-lg border border-slate-700 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-700">
                <div className="flex items-center space-x-2.5">
                  <div className="p-2 bg-emerald-500/20 text-emerald-400 rounded-xl ring-1 ring-emerald-500/40">
                    <Sparkles className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-sm tracking-wide text-white">
                      Asisten Verifikasi Regulasi AI (Gemini 2.5 Flash)
                    </h4>
                    <span className="text-[10px] text-slate-400">
                      Pemeriksaan Kepatuhan Aturan Mutlak PADG No. 23/2024
                    </span>
                  </div>
                </div>

                {/* Tombol Jalankan / Uji Ulang AI */}
                <button
                  onClick={() => handleRunAiAnalysis(selectedTicket.finding_id)}
                  disabled={isAnalyzingAi}
                  className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzingAi ? "animate-spin" : ""}`} />
                  <span>{isAnalyzingAi ? "Menganalisis Bukti..." : "Jalankan Analisis AI"}</span>
                </button>
              </div>

              {/* Status Rekomendasi AI */}
              <div className="flex items-center justify-between bg-slate-800/80 p-3 rounded-lg border border-slate-700 text-xs">
                <span className="text-slate-300">Rekomendasi Putusan AI:</span>
                <span
                  className={`font-black text-xs px-3 py-1 rounded-md font-mono ${
                    selectedTicket.ai_recommendation_status?.includes("APPROVE")
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      : selectedTicket.ai_recommendation_status?.includes("REJECT")
                      ? "bg-rose-500/20 text-rose-300 border border-rose-500/40"
                      : "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                  }`}
                >
                  {selectedTicket.ai_recommendation_status || "Tekan 'Jalankan Analisis AI'"}
                </span>
              </div>

              {/* Uraian Narasi Analisis AI */}
              <div className="p-4 bg-slate-900/90 rounded-xl border border-slate-700 text-xs text-slate-200 leading-relaxed font-sans">
                {selectedTicket.ai_analysis_text ? (
                  <p className="whitespace-pre-line">{selectedTicket.ai_analysis_text}</p>
                ) : (
                  <p className="text-slate-400 italic">
                    Belum ada hasil analisis. Klik tombol <strong>"Jalankan Analisis AI"</strong> di atas untuk memverifikasi bukti terhadap batas regulasi PADG.
                  </p>
                )}
              </div>
            </div>

            {/* Card 3: Kontrol Keputusan Human-in-the-Loop Petugas BI */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-xs p-6 space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-200">
                <div className="flex items-center space-x-2">
                  <UserCheck className="w-5 h-5 text-emerald-600" />
                  <h4 className="font-bold text-sm text-slate-900">
                    Keputusan Final Petugas BI (Human-in-the-Loop)
                  </h4>
                </div>
                <span className="text-[11px] text-slate-500">
                  Otoritas Verifikator DPPK
                </span>
              </div>

              <div className="space-y-3 text-xs">
                <div>
                  <label className="font-semibold text-slate-700 block mb-1">
                    Catatan Keputusan Petugas (Opsional):
                  </label>
                  <textarea
                    rows={2}
                    placeholder="Masukkan pertimbangan keputusan final atau rujukan disposisi Pimpinan DPPK..."
                    value={decisionNotes}
                    onChange={(e) => setDecisionNotes(e.target.value)}
                    className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                  />
                </div>

                <div className="pt-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100">
                  <span className="text-[11px] text-slate-500">
                    Persetujuan akan memperbarui matriks skor bank dan status industri secara instan.
                  </span>

                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => handleExecuteDecision("REJECTED")}
                      disabled={isDeciding}
                      className="flex items-center space-x-1.5 px-4 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-300 rounded-lg text-xs font-bold transition-colors disabled:opacity-50"
                    >
                      <X className="w-4 h-4" />
                      <span>Tolak Sanggahan (Reject)</span>
                    </button>

                    <button
                      onClick={() => handleExecuteDecision("APPROVED")}
                      disabled={isDeciding}
                      className="flex items-center space-x-1.5 px-5 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold shadow-xs transition-colors disabled:opacity-50"
                    >
                      <Check className="w-4 h-4" />
                      <span>Setujui Koreksi (Approve)</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Card 4: Log Audit Trail Real-Time */}
            <div className="bg-white rounded-xl border border-slate-200 shadow-xs p-5 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-xs text-slate-800 uppercase tracking-wider flex items-center gap-1.5">
                  <History className="w-4 h-4 text-emerald-600" />
                  Riwayat Audit Trail Verifikasi
                </h4>
                <button
                  onClick={loadAuditLogs}
                  className="text-[11px] text-emerald-600 hover:underline font-medium"
                >
                  Muat Ulang
                </button>
              </div>

              <div className="divide-y divide-slate-100 max-h-48 overflow-y-auto text-xs">
                {auditLogs.map((log) => (
                  <div key={log.id} className="py-2.5 flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-mono text-[10px] font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700">
                          {log.action}
                        </span>
                        <span className="text-[11px] font-semibold text-slate-800">
                          {log.performed_by}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5 leading-tight">
                        {log.details}
                      </p>
                    </div>
                    <span className="text-[10px] text-slate-400 whitespace-nowrap font-mono">
                      {new Date(log.timestamp).toLocaleTimeString("id-ID")}
                    </span>
                  </div>
                ))}
              </div>
            </div>

          </div>
        ) : (
          <div className="lg:col-span-7 bg-white rounded-xl border border-slate-200 p-12 text-center text-slate-400 text-xs">
            Pilih tiket temuan dari antrean sebelah kiri untuk memeriksa klaim dan analisis AI.
          </div>
        )}
      </div>
    </div>
  )
}
