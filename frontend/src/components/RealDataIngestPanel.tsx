"use client"

import React, { useRef, useState } from "react"
import { useApp } from "@/context/AppContext"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Info,
  PlayCircle,
  RefreshCw,
  UploadCloud,
} from "lucide-react"

type SourceKey = "bbg-repo" | "bbg-srbi" | "bbg-ois" | "srbi-ratio" | "repo-2m" | "srbi-3b" | "mm-ois"

interface IngestResult {
  parameter: string
  file_name: string
  period: { triwulan: string; working_days_count: number; mm_ois_sessions_count: number }
  per_bank: Array<{
    bank_id: string
    nama_singkat: string
    masked_alias: string
    rate: number | null
    detail: Record<string, any> | null
  }>
  crosscheck: { available: boolean; differences: Array<Record<string, any>> }
  unknown_banks: string[]
  source_notes?: Array<{ bank_id: string; catatan: string }>
}

interface SourceDef {
  key: SourceKey
  param: string
  title: string
  file: string
}

const GROUPS: Array<{ title: string; desc: string; sources: SourceDef[] }> = [
  {
    title: "Kuotasi Bloomberg",
    desc: "Worksheet Price Quotation Gen 2: satu sheet per bank (kode BBG), spread = |bid − ask| × 100 bps.",
    sources: [
      { key: "bbg-repo", param: "B1", title: "Kuotasi Repo (O/N ≤ 5 bps; 1 minggu & 1 bulan ≤ 20 bps)", file: "*Repo Price Quotation*.xlsx" },
      { key: "bbg-srbi", param: "B2", title: "Kuotasi SRBI (spread maks. seluruh seri ≤ 20 bps)", file: "*SRBI Price Quotation*.xlsx" },
      { key: "bbg-ois", param: "B3", title: "Kuotasi OIS (3 bulan & 12 bulan ≤ 20 bps)", file: "*OIS Price Quotation*.xlsx" },
    ],
  },
  {
    title: "Rekap Transaksi",
    desc: "Rekap volume harian per bank dari BI. Rasio SRBI juga menetapkan kalender hari kerja periode.",
    sources: [
      { key: "srbi-ratio", param: "B6", title: "Rasio penjualan SRBI sekunder vs win perdana (min. 30%)", file: "*SRBI Rasio Primer*.xlsx" },
      { key: "repo-2m", param: "B7a", title: "Transaksi Repo tenor ≥ 2 minggu (min. 60% hari kerja)", file: "*Repo 2m*.xlsx" },
      { key: "srbi-3b", param: "B7b", title: "Transaksi SRBI sisa ≥ 3 bulan (min. 60% hari kerja)", file: "*SRBI 3b*.xlsx" },
    ],
  },
  {
    title: "Matchmaking OIS",
    desc: "Export DS Antasena (sheet Kuotasi): kuotasi 1 bulan & 3 bulan di setiap sesi.",
    sources: [{ key: "mm-ois", param: "B8", title: "Partisipasi matchmaking OIS", file: "*Partisipasi MM OIS*.xlsx" }],
  },
]

const ALL_SOURCES: SourceDef[] = GROUPS.flatMap((g) => g.sources)

export const RealDataIngestPanel: React.FC = () => {
  const { refreshData, isMasked } = useApp()
  const [busy, setBusy] = useState<SourceKey | "all" | null>(null)
  const [results, setResults] = useState<Partial<Record<SourceKey, IngestResult>>>({})
  const [errors, setErrors] = useState<Partial<Record<SourceKey, string>>>({})
  const [open, setOpen] = useState<Partial<Record<SourceKey, boolean>>>({})
  const fileInputs = useRef<Partial<Record<SourceKey, HTMLInputElement | null>>>({})

  const ingestOne = async (source: SourceKey, file?: File): Promise<boolean> => {
    setErrors((e) => ({ ...e, [source]: undefined }))
    try {
      const form = new FormData()
      if (file) form.append("file", file)
      const res = await fetch(`/api/ingest/${source}`, { method: "POST", body: form })
      const json = await res.json()
      if (!res.ok) {
        setErrors((e) => ({ ...e, [source]: json.detail || "Gagal memproses file." }))
        return false
      }
      setResults((r) => ({ ...r, [source]: json }))
      return true
    } catch {
      setErrors((e) => ({ ...e, [source]: "Server backend tidak dapat dihubungi." }))
      return false
    }
  }

  const runOne = async (source: SourceKey, file?: File) => {
    setBusy(source)
    const ok = await ingestOne(source, file)
    if (ok) setOpen((o) => ({ ...o, [source]: true }))
    await refreshData()
    setBusy(null)
  }

  const runAllLocal = async () => {
    setBusy("all")
    for (const s of ALL_SOURCES) {
      await ingestOne(s.key)
    }
    await refreshData()
    setBusy(null)
  }

  const bankLabel = (b: { masked_alias: string; nama_singkat: string }) => (isMasked ? b.masked_alias : b.nama_singkat)

  const nameOf = (result: IngestResult, bankId: string) => {
    const b = result.per_bank.find((x) => x.bank_id === bankId)
    return b ? bankLabel(b) : bankId
  }

  const describeDiff = (key: SourceKey, result: IngestResult, d: Record<string, any>) => {
    const name = nameOf(result, d.bank_id)
    if (key === "mm-ois")
      return `${name} ${d.tanggal}: data mentah 1b ${d.hasil_data_mentah["1b"]} / 3b ${d.hasil_data_mentah["3b"]}, rekap BI 1b ${d.rekap_bi["1b"]} / 3b ${d.rekap_bi["3b"]}`
    if (key === "srbi-ratio") return `${name}: rasio hitung ${d.rasio_hitung_pct}%, rekap BI ${d.rasio_rekap_bi_pct}%`
    if (key === "repo-2m" || key === "srbi-3b") return `${name}: ${d.hari_hitung} hari bertransaksi, rekap BI ${d.hari_rekap_bi} hari`
    const fmt = (v: number | null) => (v === null || v === undefined ? "tidak ada kuotasi" : `${Math.round(v * 100) / 100} bps`)
    return `${name} ${d.tanggal} (${d.tenor}): data mentah ${fmt(d.spread_data_mentah)}, rekap BI ${fmt(d.spread_rekap_bi)}`
  }

  const doneCount = ALL_SOURCES.filter((s) => results[s.key]).length

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-bold text-sm text-slate-900">Data Ril Proses Kerja DPPK</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Unggah file kerja asli. Periode dibaca dari tanggal di dalam file; hasil hitung dicocokkan dengan rekap BI
            pada file yang sama. Selisih biasanya berasal dari koreksi hasil konfirmasi bank.
          </p>
        </div>
        <button
          onClick={runAllLocal}
          disabled={busy !== null}
          title="Proses ketujuh sumber dari folder dataset ril lokal (REAL_DATASET_DIR)"
          className="flex items-center gap-1.5 px-3 py-2 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold disabled:opacity-50 flex-shrink-0"
        >
          {busy === "all" ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5" />}
          {busy === "all" ? `Memproses ${doneCount}/${ALL_SOURCES.length}…` : "Proses Semua File Lokal"}
        </button>
      </div>

      {GROUPS.map((group) => (
        <div key={group.title} className="border-b border-slate-200 last:border-b-0">
          <div className="px-4 pt-3 pb-1">
            <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">{group.title}</h4>
            <p className="text-[11px] text-slate-400">{group.desc}</p>
          </div>

          {group.sources.map((src) => {
            const result = results[src.key]
            const error = errors[src.key]
            const below = result?.per_bank.filter((b) => b.rate !== null && b.rate < 100) ?? []
            const diffs = result?.crosscheck.differences ?? []
            const notes = result?.source_notes ?? []
            const isOpen = !!open[src.key]
            return (
              <div key={src.key} className="px-4 py-2.5 border-t border-slate-100 first-of-type:border-t-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 w-10 text-center">
                    {src.param}
                  </span>
                  <button
                    onClick={() => result && setOpen((o) => ({ ...o, [src.key]: !isOpen }))}
                    className={`flex-1 min-w-[12rem] text-left ${result ? "cursor-pointer" : "cursor-default"}`}
                  >
                    <div className="flex items-center gap-1 text-sm font-semibold text-slate-900">
                      {result && (isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />)}
                      {src.title}
                    </div>
                    <div className="text-[11px] font-mono text-slate-400">{result ? result.file_name : src.file}</div>
                  </button>

                  {result && (
                    <span
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                        diffs.length === 0 ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"
                      }`}
                    >
                      {below.length === 0 ? `${result.per_bank.length} bank 100%` : `${below.length} bank < 100%`}
                      {result.crosscheck.available && ` · ${diffs.length === 0 ? "cocok rekap BI" : `${diffs.length} selisih`}`}
                    </span>
                  )}

                  <div className="flex gap-1.5">
                    <input
                      type="file"
                      accept=".xlsx"
                      className="hidden"
                      ref={(el) => {
                        fileInputs.current[src.key] = el
                      }}
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f) runOne(src.key, f)
                        e.target.value = ""
                      }}
                    />
                    <button
                      onClick={() => fileInputs.current[src.key]?.click()}
                      disabled={busy !== null}
                      title="Unggah file .xlsx"
                      className="flex items-center gap-1 px-2.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
                    >
                      {busy === src.key ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
                      Unggah
                    </button>
                    <button
                      onClick={() => runOne(src.key)}
                      disabled={busy !== null}
                      title="Pakai file dari folder dataset ril lokal (REAL_DATASET_DIR)"
                      className="flex items-center gap-1 px-2.5 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold disabled:opacity-50"
                    >
                      <FolderOpen className="w-3.5 h-3.5" />
                      Lokal
                    </button>
                  </div>
                </div>

                {error && (
                  <div className="mt-2 flex items-start gap-2 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <span>{error}</span>
                  </div>
                )}

                {result && isOpen && (
                  <div className="mt-2 ml-12 space-y-2 text-xs">
                    <div className="flex items-start gap-2 p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900">
                      <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
                      <div>
                        Periode {result.period.triwulan} ·{" "}
                        {src.key === "mm-ois"
                          ? `${result.period.mm_ois_sessions_count} sesi matchmaking`
                          : `${result.period.working_days_count} hari kerja`}
                        <div className="mt-1">
                          {below.length === 0
                            ? `Seluruh ${result.per_bank.length} bank memenuhi 100%.`
                            : `Di bawah 100%: ` + below.map((b) => `${bankLabel(b)} (${b.rate}%)`).join(", ")}
                        </div>
                      </div>
                    </div>

                    {notes.length > 0 && (
                      <div className="flex items-start gap-2 p-2.5 rounded-lg bg-sky-50 border border-sky-200 text-sky-900">
                        <Info className="w-4 h-4 flex-shrink-0 mt-0.5" />
                        <ul className="space-y-0.5">
                          {notes.map((n) => (
                            <li key={n.bank_id}>
                              <strong>{nameOf(result, n.bank_id)}</strong>: {n.catatan}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {result.unknown_banks.length > 0 && (
                      <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900">
                        Nama/kode bank tidak dikenali: {result.unknown_banks.join(", ")}
                      </div>
                    )}

                    {result.crosscheck.available && diffs.length > 0 && (
                      <div className="p-2.5 rounded-lg border bg-amber-50 border-amber-200 text-amber-900">
                        <strong>Selisih vs rekap BI ({diffs.length})</strong>, kemungkinan hasil konfirmasi/sanggahan bank:
                        <ul className="mt-1.5 space-y-0.5 list-disc pl-4 max-h-48 overflow-y-auto">
                          {diffs.map((d, i) => (
                            <li key={i}>{describeDiff(src.key, result, d)}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
