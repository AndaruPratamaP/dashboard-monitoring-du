"use client"

import React, { useState } from "react"
import { useApp } from "@/context/AppContext"
import {
  Building2,
  ShieldCheck,
  AlertTriangle,
  Download,
  FileSpreadsheet,
  UploadCloud,
  FileText,
  Send,
  CheckCircle2,
  TrendingDown,
  Info,
  Mail,
  Clock,
  Check,
  Paperclip,
} from "lucide-react"

export const BankPortalView: React.FC = () => {
  const {
    matrix,
    simulatedBankId,
    setSimulatedBankId,
    isMasked,
    selectedStage,
    findings,
    refreshData,
  } = useApp()

  const [claimValue, setClaimValue] = useState("")
  const [claimReason, setClaimReason] = useState("")
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null)

  const [isSendingEws, setIsSendingEws] = useState(false)
  const [ewsReceipt, setEwsReceipt] = useState<any>(null)

  const bankData = matrix.find((m) => m.bank_id === simulatedBankId) || matrix[0]
  if (!bankData) return null

  const displayName = isMasked ? bankData.masked_alias : bankData.nama_resmi_bank
  const bankFindings = findings.filter((f) => f.bank_id === bankData.bank_id)

  const isAllPass = bankData.compliance_status === "MEMENUHI"

  // Parameter yang di bawah threshold
  const failedParams = Object.entries(bankData.passed_flags)
    .filter(([key, passed]) => !passed && key.startsWith("b"))
    .map(([key]) => key.toUpperCase())

  // Handler pengiriman email EWS otomatis
  const handleSendEwsReminder = async () => {
    setIsSendingEws(true)
    try {
      const formData = new FormData()
      formData.append("bank_id", bankData.bank_id)

      const res = await fetch("/api/notifications/ews/send-reminder", {
        method: "POST",
        body: formData,
      })
      if (res.ok) {
        const data = await res.json()
        setEwsReceipt(data.delivery_receipt)
        await refreshData()
        setTimeout(() => setEwsReceipt(null), 8000)
      }
    } catch (err) {
      console.error("Gagal mengirim pengingat EWS:", err)
    } finally {
      setIsSendingEws(false)
    }
  }

  // Handler pengajuan sanggahan oleh Bank DU
  const handleSubmitDispute = async (e: React.FormEvent, findingId: string) => {
    e.preventDefault()
    setIsSubmitting(true)
    setSubmitSuccess(null)

    try {
      const formData = new FormData()
      formData.append("finding_id", findingId)
      formData.append("nilai_klaim_bank", claimValue)
      formData.append("alasan_sanggahan", claimReason)
      if (selectedFile) {
        formData.append("file_bukti", selectedFile)
      }

      const res = await fetch("/api/disputes/submit", {
        method: "POST",
        body: formData,
      })

      if (res.ok) {
        const json = await res.json()
        setSubmitSuccess(json.message)
        setClaimValue("")
        setClaimReason("")
        setSelectedFile(null)
        await refreshData()
      } else {
        const err = await res.json()
        alert(err.detail || "Gagal mengajukan sanggahan.")
      }
    } catch (err) {
      console.error("Error submit sanggahan:", err)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      
      {/* 1. Header Banner & Profile Isolasi Bank */}
      <div className="bg-gradient-to-r from-[#0F172A] to-slate-800 text-white p-6 rounded-2xl shadow-md border border-slate-700 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center space-x-4">
          <div className="w-14 h-14 bg-emerald-600 rounded-xl flex items-center justify-center font-bold text-white text-xl shadow-lg ring-2 ring-emerald-400/40">
            {bankData.bank_id.replace("DU-", "")}
          </div>
          <div>
            <div className="flex items-center space-x-2 text-xs text-slate-300">
              <span className="bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 px-2 py-0.5 rounded font-mono font-bold">
                {bankData.bank_id}
              </span>
              <span>·</span>
              <span>{bankData.kelompok_kbmi}</span>
              <span>·</span>
              <span className="text-emerald-400 font-semibold">Portal Mandiri Dealer Utama</span>
            </div>
            <h2 className="text-xl font-extrabold text-white mt-1">
              {displayName}
            </h2>
            <p className="text-xs text-slate-400">
              Akses Terisolasi Khusus Dealer Utama · Data Bank Lain Tidak Dapat Dilihat (Privacy Protected)
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <a
            href={`/api/export/worksheet/${bankData.bank_id}`}
            download
            className="flex items-center space-x-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-md transition-all"
          >
            <FileSpreadsheet className="w-4 h-4" />
            <span>Unduh Worksheet Rekap Bank (.xlsx)</span>
          </a>
        </div>
      </div>

      {/* 2. Early Warning System (EWS Banner) jika ada parameter di bawah threshold */}
      {failedParams.length > 0 && (
        <div className="bg-gradient-to-r from-rose-50 via-amber-50 to-rose-50 border-2 border-rose-300 rounded-2xl p-5 shadow-sm space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center space-x-3">
              <div className="p-2.5 bg-rose-600 text-white rounded-xl shadow-xs">
                <AlertTriangle className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <div className="flex items-center space-x-2">
                  <h3 className="font-extrabold text-sm text-rose-950 tracking-tight">
                    PERINGATAN DINI: EARLY WARNING SYSTEM (EWS) AKTIF
                  </h3>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-200 text-rose-900 font-mono">
                    {failedParams.length} Parameter Di Bawah Threshold
                  </span>
                </div>
                <p className="text-xs text-rose-800 mt-0.5">
                  Bank Anda terdeteksi belum memenuhi kewajiban kuartalan pada indikator:{" "}
                  <strong>{failedParams.join(", ")}</strong> terhadap ambang batas tahap{" "}
                  <strong>{selectedStage}</strong> (PADG No. 23/2024). Segera ajukan sanggahan atau penuhi kuota transaksi sebelum penutupan periode!
                </p>
              </div>
            </div>

            {/* Tombol Kirim Pengingat Email Otomatis */}
            <button
              onClick={handleSendEwsReminder}
              disabled={isSendingEws}
              className="flex items-center space-x-1.5 px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-xl text-xs font-bold shadow-xs transition-colors disabled:opacity-50"
            >
              <Mail className="w-4 h-4" />
              <span>{isSendingEws ? "Mengirimkan Notifikasi..." : "Kirim Pengingat Email Otomatis"}</span>
            </button>
          </div>

          {/* Struk pengiriman email otomatis */}
          {ewsReceipt && (
            <div className="bg-white/90 p-3 rounded-xl border border-rose-200 text-xs text-slate-700 flex items-center justify-between shadow-xs animate-in fade-in duration-200">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                <span>
                  Email peringatan resmi terkirim ke <strong>{ewsReceipt.recipient}</strong> pada {new Date(ewsReceipt.sent_at).toLocaleTimeString("id-ID")}.
                </span>
              </div>
              <span className="text-[10px] text-slate-400 font-mono">
                Ref ID: EWS-{bankData.bank_id}-Q2
              </span>
            </div>
          )}
        </div>
      )}

      {/* 3. Scorecard Khusus Bank DU Tersebut */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
            Status Kepatuhan Triwulan
          </span>
          <div className="mt-1 flex items-center space-x-2">
            {isAllPass ? (
              <>
                <ShieldCheck className="w-6 h-6 text-emerald-600" />
                <span className="text-lg font-bold text-emerald-700">MEMENUHI SELURUH ATURAN</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-6 h-6 text-rose-600" />
                <span className="text-lg font-bold text-rose-700">
                  {bankData.compliance_status === "PEMBINAAN_DSMM" ? "PERLU PEMBINAAN DSMM" : "SANKSI TEGURAN TERTULIS"}
                </span>
              </>
            )}
          </div>
          <span className="text-xs text-slate-500 mt-1 block">
            Berdasarkan ambang batas tahap <strong>{selectedStage}</strong> (PADG No. 23/2024).
          </span>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
            Total Capaian Skor PUVA
          </span>
          <div className="text-2xl font-black text-slate-900 mt-1">
            {bankData.total_puva_score.toFixed(1)}% <span className="text-xs font-normal text-slate-400">/ 60%</span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-2 mt-2 overflow-hidden">
            <div
              className="bg-emerald-600 h-2 rounded-full"
              style={{ width: `${(bankData.total_puva_score / 60) * 100}%` }}
            />
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
            Simulasi Komposit Total
          </span>
          <div className="text-2xl font-black text-emerald-700 mt-1">
            {bankData.composite_score.toFixed(1)}% <span className="text-xs font-normal text-slate-400">/ 100%</span>
          </div>
          <span className="text-xs text-slate-500 mt-1 block">
            PUVA {bankData.total_puva_score.toFixed(1)}% + Operasi Moneter {bankData.total_om_score.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* 4. Rincian Capaian 9 Indikator PUVA */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs space-y-4">
        <h3 className="font-bold text-sm text-slate-900 flex items-center justify-between">
          <span>Scorecard Kepatuhan 9 Parameter PUVA ({displayName})</span>
          <span className="text-xs font-normal text-slate-400">Tahap {selectedStage}</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"].map((code) => {
            const raw = bankData.raw_metrics[code] || 0
            const passed = bankData.passed_flags[code] || false
            const score = bankData.weighted_scores[code] || 0

            return (
              <div
                key={code}
                className={`p-4 rounded-xl border text-xs flex flex-col justify-between space-y-2 ${
                  passed
                    ? "bg-emerald-50/50 border-emerald-200 text-emerald-900"
                    : "bg-rose-50/70 border-rose-300 text-rose-900"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold font-mono text-sm">{code}</span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      passed ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
                    }`}
                  >
                    {passed ? "Memenuhi" : "Di Bawah Threshold"}
                  </span>
                </div>

                <div className="flex items-baseline justify-between">
                  <span className="text-xl font-black">{raw.toFixed(1)}%</span>
                  <span className="font-mono text-xs opacity-75 font-semibold">
                    Skor: {score.toFixed(1)}p
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 5. Daftar Finding_ID & Formulir Pengajuan Sanggahan */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-xs space-y-5">
        <div className="flex items-center justify-between pb-3 border-b border-slate-200">
          <div>
            <h3 className="font-bold text-sm text-slate-900 flex items-center gap-2">
              <span>Paket Konfirmasi & Formulir Pengajuan Sanggahan</span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-700">
                {bankFindings.length} Tiket
              </span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Dealer Utama berhak mengajukan klarifikasi data dan melampirkan berkas bukti sah sebelum batas akhir evaluasi.
            </p>
          </div>
        </div>

        {submitSuccess && (
          <div className="p-4 bg-emerald-50 border border-emerald-300 rounded-xl text-emerald-900 text-xs flex items-center space-x-2 font-medium animate-in fade-in duration-200">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
            <span>{submitSuccess} Status tiket telah diperbarui menjadi PENDING_REVIEW.</span>
          </div>
        )}

        {bankFindings.length > 0 ? (
          <div className="space-y-6">
            {bankFindings.map((finding) => (
              <div
                key={finding.finding_id}
                className="p-5 rounded-xl border border-slate-200 bg-slate-50/50 space-y-4"
              >
                {/* Finding Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-200">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-xs font-extrabold px-2.5 py-1 rounded bg-slate-800 text-white">
                      {finding.finding_id}
                    </span>
                    <span className="font-bold text-xs text-slate-800">
                      Parameter {finding.parameter_code}
                    </span>
                  </div>

                  <span
                    className={`text-xs font-bold px-2.5 py-0.5 rounded-full ${
                      finding.bi_decision_status === "APPROVED"
                        ? "bg-emerald-100 text-emerald-800"
                        : finding.bi_decision_status === "REJECTED"
                        ? "bg-rose-100 text-rose-800"
                        : finding.bi_decision_status === "PENDING_REVIEW"
                        ? "bg-blue-100 text-blue-800"
                        : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    Status: {finding.bi_decision_status}
                  </span>
                </div>

                {/* Initial Data */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 bg-white rounded-lg border border-slate-200">
                    <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                      Rekap Awal Feeder BI:
                    </span>
                    <strong className="text-rose-700 text-sm">{finding.nilai_rekap_bi}</strong>
                  </div>

                  <div className="p-3 bg-white rounded-lg border border-slate-200">
                    <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                      Klaim Sanggahan Bank Terakhir:
                    </span>
                    <strong className="text-emerald-700 text-sm">
                      {finding.nilai_klaim_bank || "[Belum Diajukan]"}
                    </strong>
                  </div>
                </div>

                {/* Form Input Sanggahan */}
                <form
                  onSubmit={(e) => handleSubmitDispute(e, finding.finding_id)}
                  className="space-y-3 pt-2 text-xs"
                >
                  <div>
                    <label className="font-semibold text-slate-700 block mb-1">
                      Angka Realisasi yang Diklaim Bank:
                    </label>
                    <input
                      type="text"
                      placeholder="Misal: 85.00% (51/60 Hari Kerja)"
                      defaultValue={finding.nilai_klaim_bank || ""}
                      onChange={(e) => setClaimValue(e.target.value)}
                      required
                      className="w-full p-2.5 bg-white rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                    />
                  </div>

                  <div>
                    <label className="font-semibold text-slate-700 block mb-1">
                      Uraian Alasan Sanggahan Resmi:
                    </label>
                    <textarea
                      rows={3}
                      placeholder="Jelaskan alasan sanggahan berdasarkan data transaksi, log helpdesk, atau bukti settlement..."
                      defaultValue={finding.alasan_sanggahan || ""}
                      onChange={(e) => setClaimReason(e.target.value)}
                      required
                      className="w-full p-2.5 bg-white rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-emerald-500 leading-relaxed"
                    />
                  </div>

                  <div>
                    <label className="font-semibold text-slate-700 block mb-1">
                      Unggah File Bukti (.pdf / .xlsx / .png):
                    </label>
                    <div className="flex items-center space-x-3">
                      <label className="flex-1 p-3 border-2 border-dashed border-slate-300 rounded-lg flex items-center justify-center space-x-2 text-slate-500 cursor-pointer hover:bg-slate-100 transition-colors bg-white">
                        <UploadCloud className="w-5 h-5 text-emerald-600" />
                        <span className="truncate">
                          {selectedFile ? selectedFile.name : (finding.file_bukti_name || "Pilih berkas bukti konfirmasi...")}
                        </span>
                        <input
                          type="file"
                          accept=".pdf,.xlsx,.xls,.png,.jpg"
                          onChange={(e) => {
                            if (e.target.files && e.target.files[0]) {
                              setSelectedFile(e.target.files[0])
                            }
                          }}
                          className="hidden"
                        />
                      </label>
                    </div>
                  </div>

                  <div className="pt-2 flex justify-end">
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="flex items-center space-x-1.5 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-semibold shadow-xs transition-colors disabled:opacity-50"
                    >
                      <Send className="w-4 h-4" />
                      <span>{isSubmitting ? "Mengirimkan Sanggahan..." : "Kirim Formulir Sanggahan"}</span>
                    </button>
                  </div>
                </form>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center bg-emerald-50 rounded-xl border border-emerald-200 text-xs text-emerald-800 space-y-1">
            <CheckCircle2 className="w-8 h-8 text-emerald-600 mx-auto mb-2" />
            <h4 className="font-bold text-sm">Tidak Ada Tiket Temuan</h4>
            <p className="text-emerald-700">
              Bank Anda telah memenuhi seluruh 9 indikator PUVA pada tahap {selectedStage} (100% Kepatuhan Penuh).
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
