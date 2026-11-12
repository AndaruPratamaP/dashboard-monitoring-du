"use client"

import React, { useRef, useState } from "react"
import { useApp } from "@/context/AppContext"
import { AlertTriangle, CheckCircle2, FolderOpen, RefreshCw, UploadCloud } from "lucide-react"

type SourceKey = "srbi-ratio" | "mm-ois"

interface IngestResult {
  parameter: string
  file_name: string
  period: { triwulan: string; working_days_count: number; mm_ois_sessions_count: number }
  per_bank: Array<{
    bank_id: string
    nama_singkat: string
    masked_alias: string
    rate: number | null
    detail: Record<string, number | null> | null
  }>
  crosscheck: { available: boolean; differences: Array<Record<string, any>> }
  unknown_banks: string[]
}

const SOURCES: Array<{ key: SourceKey; param: string; title: string; file: string; desc: string }> = [
  {
    key: "srbi-ratio",
    param: "B6",
    title: "Rasio Penjualan SRBI Sekunder",
    file: "Rekap Transaksi SRBI Rasio Primer_TW*.xlsx",
    desc: "Penjualan sekunder harian vs win lelang perdana (kumulatif triwulan, min. 30%). Juga menetapkan kalender hari kerja periode.",
  },
  {
    key: "mm-ois",
    param: "B8",
    title: "Partisipasi Matchmaking OIS",
    file: "Rekap Kewajiban Partisipasi MM OIS_TW*.xlsx",
    desc: "Sheet Kuotasi (export DS Antasena): bank wajib memasang kuotasi tenor 1 & 3 bulan di setiap sesi.",
  },
]

export const RealDataIngestPanel: React.FC = () => {
  const { refreshData, isMasked } = useApp()
  const [busy, setBusy] = useState<SourceKey | null>(null)
  const [results, setResults] = useState<Partial<Record<SourceKey, IngestResult>>>({})
  const [errors, setErrors] = useState<Partial<Record<SourceKey, string>>>({})
  const fileInputs = useRef<Partial<Record<SourceKey, HTMLInputElement | null>>>({})

  const runIngest = async (source: SourceKey, file?: File) => {
    setBusy(source)
    setErrors((e) => ({ ...e, [source]: undefined }))
    try {
      const form = new FormData()
      if (file) form.append("file", file)
      const res = await fetch(`/api/ingest/${source}`, { method: "POST", body: form })
      const json = await res.json()
      if (!res.ok) {
        setErrors((e) => ({ ...e, [source]: json.detail || "Gagal memproses file." }))
        return
      }
      setResults((r) => ({ ...r, [source]: json }))
      await refreshData()
    } catch (err) {
      setErrors((e) => ({ ...e, [source]: "Server backend tidak dapat dihubungi." }))
    } finally {
      setBusy(null)
    }
  }

  const bankLabel = (b: { masked_alias: string; nama_singkat: string }) => (isMasked ? b.masked_alias : b.nama_singkat)

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200">
        <h3 className="font-bold text-sm text-slate-900">Data Ril Proses Kerja DPPK</h3>
        <p className="text-xs text-slate-500 mt-0.5">
          Unggah file kerja asli. Periode evaluasi dibaca dari tanggal di dalam file, lalu hasilnya dicocokkan
          dengan rekap BI pada file yang sama.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-slate-200">
        {SOURCES.map((src) => {
          const result = results[src.key]
          const error = errors[src.key]
          const below100 = result?.per_bank.filter((b) => b.rate !== null && b.rate < 100) ?? []
          return (
            <div key={src.key} className="p-5 space-y-3">
              <div>
                <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                  {src.param}
                </span>
                <h4 className="font-bold text-sm text-slate-900 mt-1.5">{src.title}</h4>
                <p className="text-xs text-slate-500 mt-1">{src.desc}</p>
                <p className="text-[11px] font-mono text-slate-400 mt-1">{src.file}</p>
              </div>

              <div className="flex flex-wrap gap-2">
                <input
                  type="file"
                  accept=".xlsx"
                  className="hidden"
                  ref={(el) => {
                    fileInputs.current[src.key] = el
                  }}
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) runIngest(src.key, f)
                    e.target.value = ""
                  }}
                />
                <button
                  onClick={() => fileInputs.current[src.key]?.click()}
                  disabled={busy !== null}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
                >
                  {busy === src.key ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
                  Unggah File
                </button>
                <button
                  onClick={() => runIngest(src.key)}
                  disabled={busy !== null}
                  title="Pakai file dari folder dataset ril lokal (REAL_DATASET_DIR)"
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold disabled:opacity-50"
                >
                  <FolderOpen className="w-3.5 h-3.5" />
                  Pakai File Lokal TW III
                </button>
              </div>

              {error && (
                <div className="flex items-start gap-2 p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              {result && (
                <div className="space-y-2 text-xs">
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <div>
                      <strong>{result.file_name}</strong> → periode {result.period.triwulan}
                      {src.key === "srbi-ratio" && ` · ${result.period.working_days_count} hari kerja`}
                      {src.key === "mm-ois" && ` · ${result.period.mm_ois_sessions_count} sesi matchmaking`}
                      <div className="mt-1">
                        {below100.length === 0
                          ? `Seluruh ${result.per_bank.length} bank memenuhi 100%.`
                          : `${below100.length} bank di bawah 100%: ` +
                            below100.map((b) => `${bankLabel(b)} (${b.rate}%)`).join(", ")}
                      </div>
                    </div>
                  </div>

                  {result.unknown_banks.length > 0 && (
                    <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-900">
                      Nama/kode bank tidak dikenali: {result.unknown_banks.join(", ")}
                    </div>
                  )}

                  {result.crosscheck.available && (
                    <div
                      className={`p-3 rounded-lg border ${
                        result.crosscheck.differences.length === 0
                          ? "bg-slate-50 border-slate-200 text-slate-700"
                          : "bg-amber-50 border-amber-200 text-amber-900"
                      }`}
                    >
                      <strong>Cross-check vs rekap BI: </strong>
                      {result.crosscheck.differences.length === 0
                        ? "seluruh angka cocok."
                        : `${result.crosscheck.differences.length} selisih (kemungkinan hasil konfirmasi/sanggahan bank):`}
                      {result.crosscheck.differences.length > 0 && (
                        <ul className="mt-1.5 space-y-1 list-disc pl-4">
                          {result.crosscheck.differences.map((d, i) => (
                            <li key={i}>
                              {(() => {
                                const b = result.per_bank.find((x) => x.bank_id === d.bank_id)
                                const name = b ? bankLabel(b) : d.bank_id
                                return src.key === "mm-ois"
                                  ? `${name} ${d.tanggal}: data mentah 1b ${d.hasil_data_mentah["1b"]} / 3b ${d.hasil_data_mentah["3b"]}, rekap BI 1b ${d.rekap_bi["1b"]} / 3b ${d.rekap_bi["3b"]}`
                                  : `${name}: rasio hitung ${d.rasio_hitung_pct}%, rekap BI ${d.rasio_rekap_bi_pct}%`
                              })()}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
