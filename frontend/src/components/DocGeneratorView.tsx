"use client"

import React, { useState, useEffect } from "react"
import { useApp } from "@/context/AppContext"
import {
  FileText,
  Lock,
  Unlock,
  Download,
  CheckCircle2,
  AlertCircle,
  FileSpreadsheet,
  Printer,
  Sparkles,
  RefreshCw,
  Building2,
  ShieldCheck,
  ShieldAlert,
  Edit3,
  RotateCcw,
  Layers,
  ArrowRight,
  Clock,
  ExternalLink,
} from "lucide-react"

interface SnapshotStatus {
  period: string
  stage: string
  is_locked: boolean
  locked_at: string | null
  locked_by: string | null
  snapshot_id: string | null
  summary: {
    total_banks: number
    full_pass: number
    pembinaan: number
    sanksi: number
  }
}

interface MemoPreviewData {
  type: string
  title: string
  nomor: string
  kepada: string
  dari: string
  tanggal: string
  sifat: string
  lampiran: string
  perihal: string
  period: string
  stage: string
  default_narration: string
  summary_stats?: {
    total_banks: number
    full_pass: number
    pembinaan: number
    sanksi: number
  }
  findings?: Array<{
    finding_id: string
    bank_id: string
    bank_name: string
    parameter: string
    nilai_bi: string
    klaim_bank: string
    ai_recom: string
    decision: string
  }>
  categories?: {
    lulus: string[]
    pembinaan: Array<{ bank_name: string; score: number; notes: string }>
    sanksi: Array<{ bank_name: string; score: number; notes: string }>
  }
}

export const DocGeneratorView: React.FC = () => {
  const { selectedPeriod, selectedStage, isMasked, matrix } = useApp()

  // State
  const [activeDocTab, setActiveDocTab] = useState<"m02" | "m01" | "attachments">("m02")
  const [snapshotStatus, setSnapshotStatus] = useState<SnapshotStatus | null>(null)
  const [isLoadingStatus, setIsLoadingStatus] = useState(false)
  const [isLocking, setIsLocking] = useState(false)

  // Memo preview state
  const [previewM02, setPreviewM02] = useState<MemoPreviewData | null>(null)
  const [previewM01, setPreviewM01] = useState<MemoPreviewData | null>(null)
  const [customNarration, setCustomNarration] = useState<string>("")
  const [isEditingNarration, setIsEditingNarration] = useState(false)
  const [downloadingDoc, setDownloadingDoc] = useState<string | null>(null)
  const [notification, setNotification] = useState<{ message: string; type: "success" | "error" } | null>(null)

  // 1. Fetch Snapshot Status
  const fetchSnapshotStatus = async () => {
    setIsLoadingStatus(true)
    try {
      const res = await fetch("/api/snapshot/status")
      if (res.ok) {
        const data = await res.json()
        setSnapshotStatus(data)
      }
    } catch (err) {
      console.error("Gagal mengambil status snapshot:", err)
    } finally {
      setIsLoadingStatus(false)
    }
  }

  // 2. Fetch Previews
  const fetchPreviews = async () => {
    try {
      const [res02, res01] = await Promise.all([
        fetch(`/api/export/preview/m02?masked=${isMasked}`),
        fetch(`/api/export/preview/m01?masked=${isMasked}`),
      ])

      if (res02.ok) {
        const data02: MemoPreviewData = await res02.json()
        setPreviewM02(data02)
        if (!customNarration) {
          setCustomNarration(data02.default_narration)
        }
      }

      if (res01.ok) {
        const data01: MemoPreviewData = await res01.json()
        setPreviewM01(data01)
      }
    } catch (err) {
      console.error("Gagal mengambil preview memorandum:", err)
    }
  }

  useEffect(() => {
    fetchSnapshotStatus()
    fetchPreviews()
  }, [isMasked, selectedStage, selectedPeriod])

  // Handle Snapshot Lock / Unlock
  const handleToggleLock = async () => {
    if (!snapshotStatus) return
    setIsLocking(true)
    setNotification(null)

    try {
      if (!snapshotStatus.is_locked) {
        // LOCK
        const res = await fetch("/api/snapshot/lock", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ locked_by: "Tim Evaluasi & Verifikasi DPPK" }),
        })
        if (res.ok) {
          const data = await res.json()
          setNotification({
            message: `Snapshot evaluasi berhasil dikunci dengan ID ${data.snapshot_id}. Versi data kini immutable.`,
            type: "success",
          })
          await fetchSnapshotStatus()
        }
      } else {
        // UNLOCK (Re-open)
        const res = await fetch("/api/snapshot/unlock", {
          method: "POST",
        })
        if (res.ok) {
          setNotification({
            message: "Kunci snapshot evaluasi berhasil dibuka (Re-opened). Anda dapat mengubah data atau menyimulasikan ulang.",
            type: "success",
          })
          await fetchSnapshotStatus()
        }
      }
    } catch (err) {
      setNotification({
        message: "Gagal memperbarui status snapshot. Pastikan server backend aktif.",
        type: "error",
      })
    } finally {
      setIsLocking(false)
    }
  }

  // Trigger File Download
  const handleDownloadFile = async (type: "m02" | "m01" | "attachments") => {
    setDownloadingDoc(type)
    setNotification(null)

    try {
      let url = ""

      if (type === "m02") {
        url = `/api/export/memo/m02/generate`
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            custom_narration: customNarration,
            masked: isMasked,
          }),
        })

        if (!res.ok) throw new Error("Gagal mengunduh dokumen M.02")

        const blob = await res.blob()
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = downloadUrl
        a.download = `Memorandum_M02_DPPK_Evaluasi_PUVA_${selectedPeriod}.docx`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(downloadUrl)

        setNotification({
          message: `Naskah dinas Memorandum M.02 (.docx) berhasil diunduh dengan narasi kustom.`,
          type: "success",
        })
      } else if (type === "m01") {
        url = `/api/export/memo/m01?masked=${isMasked}`
        const res = await fetch(url)
        if (!res.ok) throw new Error("Gagal mengunduh dokumen M.01")

        const blob = await res.blob()
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = downloadUrl
        a.download = `Memorandum_M01_DSMM_Evaluasi_PUVA_${selectedPeriod}.docx`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(downloadUrl)

        setNotification({
          message: `Memorandum pengantar M.01 (.docx) kepada DSMM berhasil diunduh.`,
          type: "success",
        })
      } else if (type === "attachments") {
        url = `/api/export/attachments?masked=${isMasked}`
        const res = await fetch(url)
        if (!res.ok) throw new Error("Gagal mengunduh paket lampiran")

        const blob = await res.blob()
        const downloadUrl = window.URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = downloadUrl
        a.download = `Paket_3_Lampiran_Resmi_PUVA_${selectedPeriod}.xlsx`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(downloadUrl)

        setNotification({
          message: `File Excel Paket 3 Lampiran Resmi (.xlsx) 3 sheets berhasil diunduh.`,
          type: "success",
        })
      }
    } catch (err: any) {
      setNotification({
        message: err.message || "Gagal mengunduh berkas resmi.",
        type: "error",
      })
    } finally {
      setDownloadingDoc(null)
    }
  }

  const isLocked = snapshotStatus?.is_locked ?? false

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            Evaluation Snapshot & Automated Document Generator
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-300">
              M.02, M.01 & 3-Lampiran Engine
            </span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Pembekuan versi akhir evaluasi pasca-rekonsiliasi dan pembuatan otomatis naskah dinas resmi Word (.docx) & Excel (.xlsx) sesuai PBI No. 6/2024 & PADG No. 23/2024.
          </p>
        </div>

        {/* Snapshot Locking Button */}
        <button
          onClick={handleToggleLock}
          disabled={isLocking}
          className={`flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs font-bold shadow-sm transition-all ${
            isLocked
              ? "bg-amber-600 hover:bg-amber-700 text-white ring-2 ring-amber-300"
              : "bg-slate-900 hover:bg-slate-800 text-white hover:ring-2 hover:ring-slate-400"
          } ${isLocking ? "opacity-60 cursor-not-allowed" : ""}`}
        >
          {isLocking ? (
            <RefreshCw className="w-4 h-4 animate-spin text-white" />
          ) : isLocked ? (
            <>
              <Lock className="w-4 h-4 text-amber-200" />
              <span>Buka Kunci (Re-open)</span>
            </>
          ) : (
            <>
              <Lock className="w-4 h-4 text-emerald-400" />
              <span>Kunci Snapshot Evaluasi ({selectedPeriod})</span>
            </>
          )}
        </button>
      </div>

      {/* Toast Notification */}
      {notification && (
        <div
          className={`p-3.5 rounded-xl border flex items-center justify-between text-xs transition-all ${
            notification.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-900"
              : "bg-rose-50 border-rose-200 text-rose-900"
          }`}
        >
          <div className="flex items-center space-x-2">
            {notification.type === "success" ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            )}
            <span className="font-medium">{notification.message}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="text-[11px] underline opacity-70 hover:opacity-100"
          >
            Tutup
          </button>
        </div>
      )}

      {/* Snapshot Lock Banner */}
      <div
        className={`p-4 rounded-xl border flex flex-wrap items-center justify-between gap-4 text-xs transition-all ${
          isLocked
            ? "bg-gradient-to-r from-amber-50 to-amber-100/60 border-amber-300 text-amber-950 shadow-xs"
            : "bg-slate-100 border-slate-200 text-slate-700"
        }`}
      >
        <div className="flex items-center space-x-3">
          <div
            className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
              isLocked ? "bg-amber-600 text-white shadow-xs" : "bg-slate-300 text-slate-700"
            }`}
          >
            {isLocked ? <Lock className="w-5 h-5" /> : <Unlock className="w-5 h-5" />}
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <strong className="text-sm font-bold">
                {isLocked
                  ? `SNAPSHOT TERKUNCI: ${snapshotStatus?.snapshot_id || "SNP-2026Q2-FINAL"}`
                  : "DRAF EVALUASI AKTIF (UNLOCKED)"}
              </strong>
              <span
                className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                  isLocked
                    ? "bg-amber-200 text-amber-900 border border-amber-300"
                    : "bg-slate-200 text-slate-700"
                }`}
              >
                {isLocked ? "Versi Immutable" : "Draf Kerja"}
              </span>
            </div>
            <p className="opacity-85 text-[11px] mt-0.5 max-w-2xl">
              {isLocked
                ? `Matriks skor dan tiket sanggahan telah dibekukan pada ${
                    snapshotStatus?.locked_at
                      ? new Date(snapshotStatus.locked_at).toLocaleString("id-ID")
                      : "Sesi Aktif"
                  } oleh ${snapshotStatus?.locked_by || "Tim Evaluasi DPPK"}. Seluruh dokumen M.02, M.01, dan Lampiran 1-3 dijamin 100% konsisten.`
                : "Data evaluasi masih dapat diperbarui melalui rekonsiliasi sanggahan atau simulasi ulang threshold. Kunci snapshot sebelum menerbitkan dokumen resmi."}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-3 text-right">
          <div className="bg-white/80 backdrop-blur-xs px-3 py-1.5 rounded-lg border border-slate-200/80 shadow-2xs">
            <div className="text-[10px] text-slate-500 font-medium">Periode & Ambang Batas</div>
            <div className="font-bold text-slate-800">
              {selectedPeriod} • {selectedStage}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation Tabs for Document Center */}
      <div className="flex items-center space-x-2 border-b border-slate-200 pb-2">
        <button
          onClick={() => setActiveDocTab("m02")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeDocTab === "m02"
              ? "bg-slate-900 text-white shadow-xs"
              : "bg-white text-slate-600 hover:bg-slate-100 border border-slate-200"
          }`}
        >
          <FileText className="w-4 h-4 text-emerald-400" />
          <span>Memorandum M.02 (Pimpinan DPPK)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300">
            .docx
          </span>
        </button>

        <button
          onClick={() => setActiveDocTab("m01")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeDocTab === "m01"
              ? "bg-slate-900 text-white shadow-xs"
              : "bg-white text-slate-600 hover:bg-slate-100 border border-slate-200"
          }`}
        >
          <FileText className="w-4 h-4 text-blue-400" />
          <span>Memorandum M.01 (DSMM)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded bg-blue-500/20 text-blue-300">
            .docx
          </span>
        </button>

        <button
          onClick={() => setActiveDocTab("attachments")}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
            activeDocTab === "attachments"
              ? "bg-slate-900 text-white shadow-xs"
              : "bg-white text-slate-600 hover:bg-slate-100 border border-slate-200"
          }`}
        >
          <FileSpreadsheet className="w-4 h-4 text-emerald-500" />
          <span>Paket 3 Lampiran Resmi (Sheet 1, 2, 3)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-100 text-emerald-800">
            .xlsx
          </span>
        </button>
      </div>

      {/* ==================================================================== */}
      {/* TAB 1: MEMORANDUM M.02 (KEPADA PIMPINAN DPPK)                        */}
      {/* ==================================================================== */}
      {activeDocTab === "m02" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left 2 Cols: Interactive Document Paper Preview */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8 max-w-4xl font-serif text-slate-800 space-y-6">
              {/* Header Bank Indonesia */}
              <div className="text-center border-b-2 border-slate-900 pb-4">
                <h1 className="text-lg font-black tracking-widest text-slate-950 font-sans uppercase">
                  BANK INDONESIA
                </h1>
                <h2 className="text-xs font-bold tracking-wider text-slate-600 font-sans uppercase mt-0.5">
                  DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN
                </h2>
                <div className="inline-block mt-2 px-3 py-0.5 bg-slate-900 text-white font-sans text-xs font-bold tracking-widest uppercase rounded">
                  MEMORANDUM (M.02)
                </div>
              </div>

              {/* Metadata Table */}
              <div className="font-sans text-xs grid grid-cols-6 gap-y-1.5 bg-slate-50 p-4 rounded-xl border border-slate-200">
                <div className="col-span-1 font-bold text-slate-500">Nomor</div>
                <div className="col-span-5 font-mono font-semibold text-slate-800">
                  {previewM02?.nomor || "MEMO-2026/DPPK/PUVA/M.02/084"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Kepada</div>
                <div className="col-span-5 font-bold text-slate-900">
                  {previewM02?.kepada || "Yth. Kepala Departemen Pengembangan Pasar Keuangan (DPPK)"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Dari</div>
                <div className="col-span-5 font-medium text-slate-800">
                  {previewM02?.dari || "Tim Evaluasi & Pengawasan Pasar Uang dan Pasar Valas (DPPK)"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Tanggal</div>
                <div className="col-span-5 text-slate-700">
                  {previewM02?.tanggal || new Date().toLocaleDateString("id-ID", { dateStyle: "long" })}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Sifat</div>
                <div className="col-span-5 font-semibold text-rose-700">
                  RAHASIA / SEGERA
                </div>

                <div className="col-span-1 font-bold text-slate-500">Perihal</div>
                <div className="col-span-5 font-bold text-slate-900">
                  {previewM02?.perihal || `Laporan Hasil Evaluasi Triwulanan Kewajiban Dealer Utama PUVA Periode ${selectedPeriod}`}
                </div>
              </div>

              {/* 1. Latar Belakang */}
              <div className="space-y-2">
                <h3 className="font-sans text-xs font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-1.5 h-3.5 bg-slate-900 rounded-xs"></span>
                  1. Latar Belakang dan Landasan Hukum
                </h3>
                <p className="text-xs leading-relaxed text-slate-700 text-justify">
                  1.1. Merujuk Peraturan Bank Indonesia (PBI) No. 6 Tahun 2024 tentang Pasar Uang dan Pasar Valuta Asing serta Peraturan Anggota Dewan Gubernur (PADG) No. 23 Tahun 2024 tentang Tata Cara Penetapan, Evaluasi, dan Kewajiban Dealer Utama Pasar Uang dan Pasar Valuta Asing (DU PUVA).
                </p>
                <p className="text-xs leading-relaxed text-slate-700 text-justify">
                  1.2. Telah dilaksanakan kegiatan evaluasi triwulanan kepatuhan atas 21 (dua puluh satu) Bank Dealer Utama untuk periode <strong>{selectedPeriod}</strong> (60 hari kerja aktif) pada tahap ambang batas aktif <strong>{selectedStage} STATE</strong>.
                </p>
              </div>

              {/* 2. Ringkasan Eksekutif & Narasi */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-sans text-xs font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                    <span className="w-1.5 h-3.5 bg-emerald-600 rounded-xs"></span>
                    2. Ringkasan Eksekutif Hasil Evaluasi
                  </h3>
                  <button
                    onClick={() => setIsEditingNarration(!isEditingNarration)}
                    className="font-sans text-[11px] font-semibold text-emerald-700 hover:text-emerald-800 flex items-center gap-1"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>{isEditingNarration ? "Selesai Mengedit" : "Edit Narasi Pimpinan"}</span>
                  </button>
                </div>

                {/* Editable Narration Box */}
                {isEditingNarration ? (
                  <div className="space-y-2 font-sans bg-amber-50/70 p-3.5 rounded-xl border border-amber-300">
                    <div className="flex items-center justify-between text-[11px] text-amber-900 font-semibold">
                      <span>Mode Pengeditan Narasi Eksekutif</span>
                      <button
                        onClick={() => setCustomNarration(previewM02?.default_narration || "")}
                        className="text-[10px] text-amber-700 underline flex items-center gap-1"
                      >
                        <RotateCcw className="w-3 h-3" /> Reset ke Draf Standar
                      </button>
                    </div>
                    <textarea
                      rows={4}
                      value={customNarration}
                      onChange={(e) => setCustomNarration(e.target.value)}
                      className="w-full text-xs p-2.5 rounded-lg border border-amber-300 bg-white focus:outline-hidden focus:ring-2 focus:ring-amber-500 font-sans"
                    />
                    <p className="text-[10px] text-amber-800 italic">
                      Perubahan narasi ini akan langsung dimasukkan ke dalam file Word (.docx) saat Anda mengklik tombol "Unduh M.02".
                    </p>
                  </div>
                ) : (
                  <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-200 font-sans text-xs text-slate-700 leading-relaxed text-justify">
                    {customNarration || previewM02?.default_narration}
                  </div>
                )}

                {/* Summary Table */}
                <div className="overflow-hidden rounded-xl border border-slate-200 font-sans text-[11px]">
                  <table className="w-full text-left">
                    <thead className="bg-slate-900 text-white">
                      <tr>
                        <th className="p-2.5">Kategori Status</th>
                        <th className="p-2.5 text-center">Sebelum Rekonsiliasi</th>
                        <th className="p-2.5 text-center">Pasca Rekonsiliasi</th>
                        <th className="p-2.5">Tindak Lanjut Rekomendasi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      <tr className="hover:bg-slate-50">
                        <td className="p-2.5 font-bold text-slate-900">Lolos Penuh Seluruh Kewajiban (100%)</td>
                        <td className="p-2.5 text-center font-mono font-bold text-slate-600">16 Bank</td>
                        <td className="p-2.5 text-center font-mono font-bold text-emerald-700 bg-emerald-50/50">
                          {previewM02?.summary_stats?.full_pass || 16} Bank
                        </td>
                        <td className="p-2.5 text-emerald-700 font-medium">Dinyatakan Memenuhi Seluruh Kewajiban</td>
                      </tr>
                      <tr className="hover:bg-slate-50">
                        <td className="p-2.5 font-bold text-slate-900">Perlu Klarifikasi / Tiket Temuan</td>
                        <td className="p-2.5 text-center font-mono font-bold text-rose-600">5 Bank</td>
                        <td className="p-2.5 text-center font-mono font-bold text-slate-700">0 Bank (Selesai)</td>
                        <td className="p-2.5 text-slate-600 font-medium">Verifikasi Berkas & AI Selesai Dilakukan</td>
                      </tr>
                      <tr className="hover:bg-slate-50">
                        <td className="p-2.5 font-bold text-slate-900">Kategori Pembinaan DSMM (90 - &lt;100%)</td>
                        <td className="p-2.5 text-center font-mono font-bold text-amber-600">4 Bank</td>
                        <td className="p-2.5 text-center font-mono font-bold text-amber-700 bg-amber-50/50">
                          {previewM02?.summary_stats?.pembinaan || 4} Bank
                        </td>
                        <td className="p-2.5 text-amber-800 font-medium">Email Pembinaan Pemenuhan Disiplin Kuotasi</td>
                      </tr>
                      <tr className="hover:bg-slate-50">
                        <td className="p-2.5 font-bold text-slate-900">Kategori Sanksi Teguran Tertulis (&lt;90%)</td>
                        <td className="p-2.5 text-center font-mono font-bold text-rose-600">1 Bank</td>
                        <td className="p-2.5 text-center font-mono font-bold text-rose-700 bg-rose-50/50">
                          {previewM02?.summary_stats?.sanksi || 1} Bank
                        </td>
                        <td className="p-2.5 text-rose-700 font-bold">Surat Sanksi Administratif Teguran Tertulis</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 3. Hasil Verifikasi Sanggahan */}
              <div className="space-y-3 font-sans">
                <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-1.5 h-3.5 bg-blue-600 rounded-xs"></span>
                  3. Rincian Hasil Verifikasi Sanggahan Bank DU
                </h3>
                <div className="overflow-hidden rounded-xl border border-slate-200 text-[11px]">
                  <table className="w-full text-left">
                    <thead className="bg-slate-800 text-white">
                      <tr>
                        <th className="p-2">Finding ID</th>
                        <th className="p-2">Bank DU</th>
                        <th className="p-2 text-center">Param</th>
                        <th className="p-2 text-center">Rekap BI</th>
                        <th className="p-2 text-center">Rekomendasi AI</th>
                        <th className="p-2 text-center">Keputusan Final</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-200">
                      {previewM02?.findings?.map((f) => (
                        <tr key={f.finding_id} className="hover:bg-slate-50">
                          <td className="p-2 font-mono font-bold text-slate-700">{f.finding_id}</td>
                          <td className="p-2 font-medium text-slate-900">{f.bank_name}</td>
                          <td className="p-2 text-center font-bold text-slate-700">{f.parameter}</td>
                          <td className="p-2 text-center text-slate-600">{f.nilai_bi}</td>
                          <td className="p-2 text-center font-bold">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] ${
                                f.ai_recom === "APPROVE"
                                  ? "bg-emerald-100 text-emerald-800"
                                  : "bg-rose-100 text-rose-800"
                              }`}
                            >
                              {f.ai_recom}
                            </span>
                          </td>
                          <td className="p-2 text-center font-bold">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] ${
                                f.decision === "APPROVED"
                                  ? "bg-emerald-600 text-white"
                                  : f.decision === "REJECTED"
                                  ? "bg-rose-600 text-white"
                                  : "bg-amber-500 text-white"
                              }`}
                            >
                              {f.decision}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 4. Permohonan Persetujuan & Lembar Tanda Tangan */}
              <div className="space-y-4 font-sans text-xs pt-4 border-t border-slate-200">
                <p className="leading-relaxed text-slate-700 text-justify">
                  Sehubungan dengan hasil evaluasi di atas, bersama ini kami memohon perkenan Bapak Kepala Departemen Pengembangan Pasar Keuangan untuk menyetujui laporan evaluasi ini serta mengesahkan penerusan berkas Memorandum M.01 ke Departemen Surveilans & Manajemen Risiko (DSMM).
                </p>

                <div className="grid grid-cols-2 gap-8 pt-4">
                  <div>
                    <div className="text-[11px] text-slate-500">Disiapkan Oleh:</div>
                    <div className="font-bold text-slate-900 mt-1">Tim Evaluasi PUVA DPPK</div>
                    <div className="h-16"></div>
                    <div className="font-bold text-slate-800 border-t border-slate-300 pt-1 inline-block">
                      Analis Senior PUVA
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] text-slate-500">Menyetujui:</div>
                    <div className="font-bold text-slate-900 mt-1">Kepala Departemen DPPK</div>
                    <div className="h-16"></div>
                    <div className="font-bold text-slate-800 border-t border-slate-300 pt-1 inline-block">
                      Donny Hutabarat / Direktur Eksekutif
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Col: Action & Download Panel */}
          <div className="space-y-4">
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-900 text-white">
                    M.02
                  </span>
                  <span className="text-xs font-bold text-slate-800">Naskah Dinas Word</span>
                </div>
                <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                  Resmi Pimpinan
                </span>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                Dokumen Memorandum M.02 siap diekspor ke format <strong>Microsoft Word (.docx)</strong> dengan format surat dinas resmi Bank Indonesia, lengkap dengan tabel ringkasan eksekutif, rekapitulasi 5 sanggahan, dan permohonan persetujuan pimpinan.
              </p>

              <div className="space-y-2 pt-2">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Target Audiens:</span>
                  <strong className="text-slate-800">Pimpinan DPPK</strong>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Format Berkas:</span>
                  <span className="font-mono font-medium text-slate-700">.docx (OpenXML)</span>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Mode Privasi:</span>
                  <span className="font-semibold text-slate-700">
                    {isMasked ? "Mode Alias (Bank A - Bank U)" : "Nama Resmi Bank"}
                  </span>
                </div>
              </div>

              <div className="pt-4 border-t border-slate-100">
                <button
                  onClick={() => handleDownloadFile("m02")}
                  disabled={downloadingDoc === "m02"}
                  className="w-full flex items-center justify-center space-x-2 py-3 px-4 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold shadow-md hover:shadow-lg transition-all"
                >
                  {downloadingDoc === "m02" ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  <span>Unduh Memorandum M.02 (.docx)</span>
                </button>
              </div>
            </div>

            {/* Quick Summary Card */}
            <div className="bg-slate-900 text-white rounded-2xl p-5 shadow-sm space-y-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
                Validasi Standar PADG 23/2024
              </h4>
              <ul className="text-xs space-y-2 text-slate-300">
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                  <span>Kriteria kuotasi spread Repo maks 5/20 bps &amp; SRBI 20 bps terpenuhi.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                  <span>Tenor Repo sekunder minimal 14 hari kerja diverifikasi otomatis.</span>
                </li>
                <li className="flex items-start gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                  <span>Data snapshot beku menjamin zero-inconsistency dengan Lampiran 1-3.</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* TAB 2: MEMORANDUM M.01 (PENGANTAR KE DSMM)                           */}
      {/* ==================================================================== */}
      {activeDocTab === "m01" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-8 max-w-4xl font-serif text-slate-800 space-y-6">
              {/* Header */}
              <div className="text-center border-b-2 border-slate-900 pb-4">
                <h1 className="text-lg font-black tracking-widest text-slate-950 font-sans uppercase">
                  BANK INDONESIA
                </h1>
                <h2 className="text-xs font-bold tracking-wider text-slate-600 font-sans uppercase mt-0.5">
                  DEPARTEMEN PENGEMBANGAN PASAR KEUANGAN
                </h2>
                <div className="inline-block mt-2 px-3 py-0.5 bg-blue-900 text-white font-sans text-xs font-bold tracking-widest uppercase rounded">
                  MEMORANDUM PENGANTAR (M.01)
                </div>
              </div>

              {/* Metadata */}
              <div className="font-sans text-xs grid grid-cols-6 gap-y-1.5 bg-slate-50 p-4 rounded-xl border border-slate-200">
                <div className="col-span-1 font-bold text-slate-500">Nomor</div>
                <div className="col-span-5 font-mono font-semibold text-slate-800">
                  {previewM01?.nomor || "MEMO-2026/DPPK/PUVA/M.01/085"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Kepada</div>
                <div className="col-span-5 font-bold text-slate-900">
                  {previewM01?.kepada || "Yth. Kepala Departemen Surveilans & Manajemen Risiko (DSMM)"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Dari</div>
                <div className="col-span-5 font-medium text-slate-800">
                  {previewM01?.dari || "Kepala Departemen Pengembangan Pasar Keuangan (DPPK)"}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Tanggal</div>
                <div className="col-span-5 text-slate-700">
                  {previewM01?.tanggal || new Date().toLocaleDateString("id-ID", { dateStyle: "long" })}
                </div>

                <div className="col-span-1 font-bold text-slate-500">Perihal</div>
                <div className="col-span-5 font-bold text-slate-900">
                  {previewM01?.perihal || `Penyampaian Hasil Akhir Evaluasi Pemenuhan Kewajiban Dealer Utama PUVA Periode ${selectedPeriod} untuk Pembinaan & Pengawasan`}
                </div>
              </div>

              {/* Maksud & Tujuan */}
              <div className="space-y-2">
                <h3 className="font-sans text-xs font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-1.5 h-3.5 bg-slate-900 rounded-xs"></span>
                  1. Dasar Hukum dan Maksud Penyampaian
                </h3>
                <p className="text-xs leading-relaxed text-slate-700 text-justify font-sans">
                  Menindaklanjuti ketentuan Pasal 28 PADG No. 23 Tahun 2024, Departemen Pengembangan Pasar Keuangan (DPPK) menyampaikan hasil akhir evaluasi 21 Bank Dealer Utama PUVA periode {selectedPeriod} pasca-rekonsiliasi kepada DSMM sebagai rujukan resmi pelaksanaan pembinaan dan sanksi administratif pengawasan perbankan.
                </p>
              </div>

              {/* 3 Kategori Pengawasan Cards */}
              <div className="space-y-3 font-sans">
                <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide flex items-center gap-1.5">
                  <span className="w-1.5 h-3.5 bg-blue-600 rounded-xs"></span>
                  2. Klasifikasi Hasil Evaluasi Komposit &amp; Rekomendasi Tindak Lanjut
                </h3>

                {/* Kategori A: Memenuhi (100%) */}
                <div className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/50 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-emerald-900 flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      Kategori A: Memenuhi Seluruh Kewajiban (Skor Komposit = 100%)
                    </span>
                    <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-emerald-200 text-emerald-900">
                      {previewM01?.categories?.lulus?.length || 16} Bank Lulus
                    </span>
                  </div>
                  <p className="text-[11px] text-emerald-800">
                    <strong>Rekomendasi DSMM:</strong> Dinyatakan Lulus penuh evaluasi triwulanan Dealer Utama PUVA.
                  </p>
                  <p className="text-[11px] text-slate-600">
                    Daftar Bank: {previewM01?.categories?.lulus?.slice(0, 8).join(", ")}... dan bank lainnya.
                  </p>
                </div>

                {/* Kategori B: Pembinaan DSMM (90 - <100%) */}
                <div className="p-4 rounded-xl border border-amber-200 bg-amber-50/50 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-amber-900 flex items-center gap-1.5">
                      <Clock className="w-4 h-4 text-amber-600" />
                      Kategori B: Pembinaan Pengawasan DSMM (90.0% ≤ Skor Komposit &lt; 100%)
                    </span>
                    <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-200 text-amber-900">
                      {previewM01?.categories?.pembinaan?.length || 4} Bank
                    </span>
                  </div>
                  <p className="text-[11px] text-amber-900">
                    <strong>Rekomendasi DSMM:</strong> Penyampaian Surat / Email Pembinaan oleh DSMM terkait disiplin kuotasi pasar sekunder dan pemenuhan counterparty line.
                  </p>
                  <div className="space-y-1 pt-1">
                    {previewM01?.categories?.pembinaan?.map((b) => (
                      <div key={b.bank_name} className="text-[11px] text-slate-700 flex items-center justify-between bg-white/70 px-2 py-1 rounded border border-amber-200/50">
                        <span><strong>{b.bank_name}</strong> ({b.notes})</span>
                        <span className="font-mono font-bold text-amber-800">{b.score.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Kategori C: Sanksi Teguran (<90%) */}
                <div className="p-4 rounded-xl border border-rose-200 bg-rose-50/50 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-rose-900 flex items-center gap-1.5">
                      <ShieldAlert className="w-4 h-4 text-rose-600" />
                      Kategori C: Sanksi Administratif Teguran Tertulis (Skor Komposit &lt; 90.0%)
                    </span>
                    <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-rose-200 text-rose-900">
                      {previewM01?.categories?.sanksi?.length || 1} Bank
                    </span>
                  </div>
                  <p className="text-[11px] text-rose-900">
                    <strong>Rekomendasi DSMM:</strong> Penerbitan Surat Sanksi Administratif Teguran Tertulis sesuai Pasal 32 PADG No. 23 Tahun 2024 atas pelanggaran tenor transaksi pasar sekunder.
                  </p>
                  <div className="space-y-1 pt-1">
                    {previewM01?.categories?.sanksi?.map((b) => (
                      <div key={b.bank_name} className="text-[11px] text-slate-700 flex items-center justify-between bg-white/70 px-2 py-1 rounded border border-rose-200/50">
                        <span><strong>{b.bank_name}</strong> ({b.notes})</span>
                        <span className="font-mono font-bold text-rose-700">{b.score.toFixed(1)}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Signature */}
              <div className="pt-6 border-t border-slate-200 font-sans text-xs flex justify-end">
                <div className="text-right space-y-1">
                  <p className="font-semibold text-slate-700">Departemen Pengembangan Pasar Keuangan</p>
                  <p className="font-bold text-slate-900">Kepala Departemen,</p>
                  <div className="h-16"></div>
                  <p className="font-bold text-slate-900 underline">Donny Hutabarat</p>
                  <p className="text-[11px] text-slate-500">Direktur Eksekutif</p>
                </div>
              </div>
            </div>
          </div>

          {/* Right Col */}
          <div className="space-y-4">
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-xs space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-slate-100">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-blue-900 text-white">
                    M.01
                  </span>
                  <span className="text-xs font-bold text-slate-800">Nota Pengantar Word</span>
                </div>
                <span className="text-[10px] font-bold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                  Kepada DSMM
                </span>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                Dokumen pengantar M.01 ke Departemen Surveilans & Manajemen Risiko (DSMM) berisi penyampaian klasifikasi 3 kategori kepatuhan (Lulus 100%, Pembinaan DSMM, dan Sanksi Teguran Tertulis).
              </p>

              <div className="space-y-2 pt-2">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Penerima Memo:</span>
                  <strong className="text-slate-800">Kepala DSMM</strong>
                </div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Format Berkas:</span>
                  <span className="font-mono font-medium text-slate-700">.docx (OpenXML)</span>
                </div>
              </div>

              <div className="pt-4 border-t border-slate-100">
                <button
                  onClick={() => handleDownloadFile("m01")}
                  disabled={downloadingDoc === "m01"}
                  className="w-full flex items-center justify-center space-x-2 py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold shadow-md hover:shadow-lg transition-all"
                >
                  {downloadingDoc === "m01" ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  <span>Unduh Memorandum M.01 (.docx)</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* TAB 3: PAKET 3 LAMPIRAN EXCEL                                        */}
      {/* ==================================================================== */}
      {activeDocTab === "attachments" && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200 p-6 shadow-xs flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="flex items-center space-x-2">
                <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
                <h3 className="font-bold text-sm text-slate-900">
                  Paket Berkas 3 Lampiran Resmi (.xlsx)
                </h3>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                  Multi-Sheet Workbook
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1 max-w-2xl">
                Buku kerja Excel (.xlsx) terintegrasi yang memuat 3 sheet resmi pelengkap Memorandum M.02 & M.01 sesuai standar pelaporan Dewan Gubernur Bank Indonesia.
              </p>
            </div>

            <button
              onClick={() => handleDownloadFile("attachments")}
              disabled={downloadingDoc === "attachments"}
              className="flex items-center space-x-2 py-2.5 px-5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-bold shadow-md hover:shadow-lg transition-all"
            >
              {downloadingDoc === "attachments" ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              <span>Unduh Paket 3 Lampiran (.xlsx)</span>
            </button>
          </div>

          {/* Cards for 3 Sheets */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Sheet 1 */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-900 text-white">
                    Sheet 1
                  </span>
                  <span className="text-[10px] font-semibold text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                    Realisasi Mentah
                  </span>
                </div>
                <h4 className="font-bold text-sm text-slate-900">
                  Lampiran 1: Sebelum Threshold
                </h4>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  Matriks 21 Bank Dealer Utama yang memuat persentase capaian pemenuhan aktual pada 9 parameter PUVA (B1 s.d. B8) tanpa pembobotan threshold.
                </p>
              </div>
              <div className="pt-3 border-t border-slate-100 text-[11px] text-slate-500 font-mono">
                Kolom: B1 - B8 &amp; Rata-rata
              </div>
            </div>

            {/* Sheet 2 */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-900 text-white">
                    Sheet 2
                  </span>
                  <span className="text-[10px] font-semibold text-emerald-800 bg-emerald-100 px-2 py-0.5 rounded">
                    Terbobot &amp; Komposit
                  </span>
                </div>
                <h4 className="font-bold text-sm text-slate-900">
                  Lampiran 2: Setelah Threshold
                </h4>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  Matriks skor terbobot setelah ambang batas aktif ({selectedStage} State). Menampilkan Subtotal PUVA (maks 60%), OM (maks 40%), dan Skor Komposit 100%.
                </p>
              </div>
              <div className="pt-3 border-t border-slate-100 text-[11px] text-slate-500 font-mono">
                Kolom: Skor B1-B8, OM1-3, Komposit
              </div>
            </div>

            {/* Sheet 3 */}
            <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-xs space-y-3 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 rounded bg-slate-900 text-white">
                    Sheet 3
                  </span>
                  <span className="text-[10px] font-semibold text-amber-800 bg-amber-100 px-2 py-0.5 rounded">
                    Pengawasan &amp; Sanksi
                  </span>
                </div>
                <h4 className="font-bold text-sm text-slate-900">
                  Lampiran 3: Tindak Lanjut Bank
                </h4>
                <p className="text-xs text-slate-600 mt-2 leading-relaxed">
                  Tabel komprehensif status kelulusan 21 Bank (Lulus / Email Pembinaan DSMM / Sanksi Teguran), nomor tiket Finding ID sanggahan, dan tindak lanjut hukum.
                </p>
              </div>
              <div className="pt-3 border-t border-slate-100 text-[11px] text-slate-500 font-mono">
                Kolom: Kepatuhan &amp; Rekomendasi DSMM
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
