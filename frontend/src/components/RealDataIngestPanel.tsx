"use client"

import React, { useRef, useState } from "react"
import { useApp } from "@/context/AppContext"
import { CounterpartyLineEditor } from "@/components/CounterpartyLineEditor"
import { ReplySheetMapper } from "@/components/ReplySheetMapper"
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
      { key: "bbg-repo", param: "B1", title: "Kuotasi Repo (O/N ≤ 5 bps; 1 minggu ≤ 10 bps; 1 bulan ≤ 20 bps)", file: "*Repo Price Quotation*.xlsx" },
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

interface CpLine {
  line_du: number
  line_non_du: number
  rate: number
  dikonfirmasi_bank: boolean
  line_du_setelah_cutoff?: number
  line_non_du_setelah_cutoff?: number
  counterparty_setelah_cutoff?: string[]
}

interface ReplyBankSummary {
  bank_id: string
  workbook: Array<{ file: string; item: number; sheet: Array<{ sheet: string; jenis: string | null; catatan: string }> }>
  bukti: string[]
  manual: Array<{ file: string; alasan: string }>
  item: { baru: number; diperbarui: number; dibuka_ulang: number }
}

interface RepliesResult {
  round: { round_no: number }
  per_bank: ReplyBankSummary[]
  unassigned: Array<{ file: string; alasan: string }>
}

interface CounterpartyResult {
  period: { triwulan: string }
  applied: Array<{ file: string; bank_id: string; balasan_bank: boolean }>
  skipped: Array<{ file: string; alasan: string }>
  per_bank: Array<{ bank_id: string; nama_singkat: string; masked_alias: string; B4: CpLine | null; B5: CpLine | null }>
}

export const RealDataIngestPanel: React.FC = () => {
  const { refreshData, isMasked, banks } = useApp()
  const [busy, setBusy] = useState<SourceKey | "all" | null>(null)
  const [results, setResults] = useState<Partial<Record<SourceKey, IngestResult>>>({})
  const [errors, setErrors] = useState<Partial<Record<SourceKey, string>>>({})
  const [open, setOpen] = useState<Partial<Record<SourceKey, boolean>>>({})
  const fileInputs = useRef<Partial<Record<SourceKey, HTMLInputElement | null>>>({})
  const cpInput = useRef<HTMLInputElement | null>(null)
  const [cpBusy, setCpBusy] = useState(false)
  const [cpResult, setCpResult] = useState<CounterpartyResult | null>(null)
  const [cpError, setCpError] = useState<string | null>(null)
  const [cpOpen, setCpOpen] = useState(false)
  const [cpEdit, setCpEdit] = useState<string | null>(null)
  const rpInput = useRef<HTMLInputElement | null>(null)
  const [rpBusy, setRpBusy] = useState(false)
  const [rpResult, setRpResult] = useState<RepliesResult | null>(null)
  const [rpError, setRpError] = useState<string | null>(null)
  const [rpOpen, setRpOpen] = useState(false)
  const { setActiveMenu } = useApp()

  const ingestReplies = async (files?: FileList): Promise<boolean> => {
    setRpError(null)
    try {
      const form = new FormData()
      if (files) Array.from(files).forEach((f) => form.append("files", f))
      const res = await fetch("/api/replies/ingest", { method: "POST", body: form })
      const json = await res.json()
      if (!res.ok) {
        setRpError(json.detail || "Gagal memproses balasan bank.")
        return false
      }
      setRpResult(json)
      return true
    } catch {
      setRpError("Server backend tidak dapat dihubungi.")
      return false
    }
  }

  const runReplies = async (files?: FileList) => {
    setRpBusy(true)
    if (await ingestReplies(files)) setRpOpen(true)
    await refreshData()
    setRpBusy(false)
  }

  const applyCpBreakdown = (bankId: string, bd: Record<string, any>) => {
    setCpResult((r) =>
      r ? { ...r, per_bank: r.per_bank.map((b) => (b.bank_id === bankId ? { ...b, B4: bd.B4 ?? b.B4, B5: bd.B5 ?? b.B5 } : b)) } : r,
    )
    refreshData()
  }

  const ingestCounterparty = async (files?: FileList): Promise<boolean> => {
    setCpError(null)
    try {
      const form = new FormData()
      if (files) Array.from(files).forEach((f) => form.append("files", f))
      const res = await fetch("/api/counterparty/ingest", { method: "POST", body: form })
      const json = await res.json()
      if (!res.ok) {
        setCpError(json.detail || "Gagal memproses workbook.")
        return false
      }
      setCpResult(json)
      return true
    } catch {
      setCpError("Server backend tidak dapat dihubungi.")
      return false
    }
  }

  const runCounterparty = async (files?: FileList) => {
    setCpBusy(true)
    if (await ingestCounterparty(files)) setCpOpen(true)
    await refreshData()
    setCpBusy(false)
  }

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
    await ingestCounterparty()
    await ingestReplies()
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
          {busy === "all" ? `Memproses ${doneCount}/${ALL_SOURCES.length + 2}…` : "Proses Semua File Lokal"}
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

      <div className="border-t border-slate-200">
        <div className="px-4 pt-3 pb-1">
          <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">Konfirmasi Bank</h4>
          <p className="text-[11px] text-slate-400">
            Workbook kiriman BI menjadi daftar awal, lalu balasan bank menimpa daftar & status line. Line &quot;Dihapus&quot;
            tidak dihitung. Diproses pada periode aktif.
          </p>
        </div>
        <div className="px-4 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 w-10 text-center">
              B4/B5
            </span>
            <button
              onClick={() => cpResult && setCpOpen(!cpOpen)}
              className={`flex-1 min-w-[12rem] text-left ${cpResult ? "cursor-pointer" : "cursor-default"}`}
            >
              <div className="flex items-center gap-1 text-sm font-semibold text-slate-900">
                {cpResult && (cpOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />)}
                Counterparty line Repo (10 DU & 10 non-DU) & OIS (10 DU)
              </div>
              <div className="text-[11px] font-mono text-slate-400">
                {cpResult
                  ? `${cpResult.applied.length} workbook diterapkan · ${cpResult.applied.filter((a) => a.balasan_bank).length} balasan bank`
                  : "Konfirmasi Bank/*.xlsx + balasan [Confirmed]"}
              </div>
            </button>
            {cpResult && (() => {
              const below = cpResult.per_bank.filter((b) => (b.B4 && b.B4.rate < 100) || (b.B5 && b.B5.rate < 100))
              const missing = cpResult.per_bank.filter((b) => !b.B4 || !b.B5)
              return (
                <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${below.length || missing.length ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
                  {below.length === 0 ? "semua ≥ 10 line" : `${below.length} bank < 10 line`}
                  {missing.length > 0 && ` · ${missing.length} tanpa data`}
                </span>
              )
            })()}
            <div className="flex gap-1.5">
              <input
                type="file"
                accept=".xlsx"
                multiple
                className="hidden"
                ref={cpInput}
                onChange={(e) => {
                  if (e.target.files?.length) runCounterparty(e.target.files)
                  e.target.value = ""
                }}
              />
              <button
                onClick={() => cpInput.current?.click()}
                disabled={busy !== null || cpBusy}
                title="Unggah satu atau beberapa workbook (.xlsx)"
                className="flex items-center gap-1 px-2.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                {cpBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
                Unggah
              </button>
              <button
                onClick={() => runCounterparty()}
                disabled={busy !== null || cpBusy}
                title="Pakai workbook dari folder dataset ril lokal"
                className="flex items-center gap-1 px-2.5 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                <FolderOpen className="w-3.5 h-3.5" />
                Lokal
              </button>
            </div>
          </div>

          {cpError && (
            <div className="mt-2 flex items-start gap-2 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{cpError}</span>
            </div>
          )}

          {cpResult && cpOpen && (
            <div className="mt-2 ml-12 space-y-2 text-xs">
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full text-left">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="p-2">Bank</th>
                      <th className="p-2 text-right">Repo DU</th>
                      <th className="p-2 text-right">Repo non-DU</th>
                      <th className="p-2 text-right">OIS DU</th>
                      <th className="p-2">Sumber</th>
                      <th className="p-2"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {cpResult.per_bank.map((b) => {
                      const low = (v: number | undefined) => (v !== undefined && v < 10 ? "text-rose-700 font-bold" : "")
                      const after = (n?: number) =>
                        n ? (
                          <span className="ml-1 px-1 rounded bg-sky-100 text-sky-800 text-[10px]" title="Termasuk line yang dibuka setelah cut-off (tetap dihitung)">
                            {n} baru
                          </span>
                        ) : null
                      return (
                        <React.Fragment key={b.bank_id}>
                          <tr>
                            <td className="p-2 font-semibold text-slate-800">{bankLabel(b)}</td>
                            <td className={`p-2 text-right font-mono ${low(b.B4?.line_du)}`}>
                              {b.B4 ? b.B4.line_du : "—"}
                              {after(b.B4?.line_du_setelah_cutoff)}
                            </td>
                            <td className={`p-2 text-right font-mono ${low(b.B4?.line_non_du)}`}>
                              {b.B4 ? b.B4.line_non_du : "—"}
                              {after(b.B4?.line_non_du_setelah_cutoff)}
                            </td>
                            <td className={`p-2 text-right font-mono ${low(b.B5?.line_du)}`}>
                              {b.B5 ? b.B5.line_du : "—"}
                              {after(b.B5?.line_du_setelah_cutoff)}
                            </td>
                            <td className="p-2 text-slate-500">
                              {!b.B4 && !b.B5 ? "belum ada workbook" : b.B4?.dikonfirmasi_bank || b.B5?.dikonfirmasi_bank ? "balasan bank" : "daftar BI (belum dibalas)"}
                            </td>
                            <td className="p-2 text-right">
                              {(b.B4 || b.B5) && (
                                <button
                                  onClick={() => setCpEdit(cpEdit === b.bank_id ? null : b.bank_id)}
                                  className="text-emerald-700 font-semibold hover:underline"
                                >
                                  {cpEdit === b.bank_id ? "Tutup" : "Koreksi"}
                                </button>
                              )}
                            </td>
                          </tr>
                          {cpEdit === b.bank_id && (
                            <tr>
                              <td colSpan={6} className="p-2">
                                <CounterpartyLineEditor bankId={b.bank_id} onChanged={(bd) => applyCpBreakdown(b.bank_id, bd)} />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-[11px] text-slate-500">
                <span className="px-1 rounded bg-sky-100 text-sky-800">n baru</span> = line yang dibuka setelah cut-off. Tetap dihitung
                (kondisi akhir periode), ditandai agar terlihat bedanya dengan line yang sudah ada sebelum cut-off.
              </p>
              {cpResult.skipped.length > 0 && (
                <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900">
                  <strong>{cpResult.skipped.length} file dilewati</strong>
                  <ul className="mt-1 space-y-0.5 list-disc pl-4">
                    {cpResult.skipped.map((sk, i) => (
                      <li key={i}>
                        <span className="font-mono">{sk.file}</span>: {sk.alasan}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="px-4 py-2.5 border-t border-slate-100">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-bold font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 w-10 text-center">
              B1–B8
            </span>
            <button
              onClick={() => rpResult && setRpOpen(!rpOpen)}
              className={`flex-1 min-w-[12rem] text-left ${rpResult ? "cursor-pointer" : "cursor-default"}`}
            >
              <div className="flex items-center gap-1 text-sm font-semibold text-slate-900">
                {rpResult && (rpOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />)}
                Balasan bank: sanggahan per tanggal
              </div>
              <div className="text-[11px] font-mono text-slate-400">
                {rpResult
                  ? `Ronde ${rpResult.round.round_no} · ${rpResult.per_bank.length} bank membalas`
                  : "[Confirmed]/<bank>/*.xlsx, *.pdf, *.png, *.jpg"}
              </div>
            </button>
            {rpResult && (() => {
              const baru = rpResult.per_bank.reduce((a, b) => a + b.item.baru, 0)
              const manual = rpResult.per_bank.reduce((a, b) => a + b.manual.length, 0)
              return (
                <span className="flex gap-1">
                  <button
                    onClick={() => setActiveMenu("reconciliation")}
                    className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 hover:underline"
                    title="Buka Reconciliation Center"
                  >
                    {baru} item baru →
                  </button>
                  {manual > 0 && (
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-rose-50 text-rose-800">
                      {manual} file perlu tindakan manual
                    </span>
                  )}
                </span>
              )
            })()}
            <div className="flex gap-1.5">
              <input
                type="file"
                accept=".xlsx,.pdf,.png,.jpg,.jpeg"
                multiple
                className="hidden"
                ref={rpInput}
                onChange={(e) => {
                  if (e.target.files?.length) runReplies(e.target.files)
                  e.target.value = ""
                }}
              />
              <button
                onClick={() => rpInput.current?.click()}
                disabled={busy !== null || rpBusy}
                title="Unggah workbook balasan & file bukti (nama file/folder menunjukkan bank)"
                className="flex items-center gap-1 px-2.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                {rpBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
                Unggah
              </button>
              <button
                onClick={() => runReplies()}
                disabled={busy !== null || rpBusy}
                title="Pakai folder balasan [Confirmed] pada dataset ril lokal"
                className="flex items-center gap-1 px-2.5 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold disabled:opacity-50"
              >
                <FolderOpen className="w-3.5 h-3.5" />
                Lokal
              </button>
            </div>
          </div>

          {rpError && (
            <div className="mt-2 flex items-start gap-2 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
              <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <span>{rpError}</span>
            </div>
          )}

          {rpResult && rpOpen && (
            <div className="mt-2 ml-12 space-y-2 text-xs">
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="w-full text-left">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="p-2">Bank</th>
                      <th className="p-2">Workbook dibaca</th>
                      <th className="p-2 text-right">Item sanggahan</th>
                      <th className="p-2">Bukti</th>
                      <th className="p-2">Perlu tindakan manual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rpResult.per_bank.map((b) => {
                      const mb = banks.find((x) => x.bank_id === b.bank_id)
                      return (
                        <tr key={b.bank_id} className="align-top">
                          <td className="p-2 font-semibold text-slate-800">{mb ? (isMasked ? mb.masked_alias : mb.nama_singkat || mb.nama_resmi_bank) : b.bank_id}</td>
                          <td className="p-2 text-slate-600">
                            {b.workbook.length === 0
                              ? "—"
                              : b.workbook.map((w) => (
                                  <div key={w.file} title={w.sheet.map((x) => `${x.sheet}: ${x.catatan}`).join("\n")}>
                                    <span className="font-mono">{w.file}</span>{" "}
                                    <span className="text-slate-400">
                                      ({w.sheet.filter((x) => x.catatan.startsWith("dibaca")).length} sheet dibaca)
                                    </span>
                                    <ReplySheetMapper bankId={b.bank_id} file={w.file} onSaved={refreshData} />
                                  </div>
                                ))}
                          </td>
                          <td className="p-2 text-right font-mono">
                            {b.item.baru}
                            {b.item.diperbarui > 0 && <span className="text-slate-400"> +{b.item.diperbarui} diperbarui</span>}
                          </td>
                          <td className="p-2 text-slate-600 font-mono">{b.bukti.join(", ") || "—"}</td>
                          <td className="p-2 text-rose-700">
                            {b.manual.map((m) => (
                              <div key={m.file}>
                                <span className="font-mono">{m.file}</span>: {m.alasan}
                              </div>
                            ))}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {rpResult.unassigned.length > 0 && (
                <div className="p-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-900">
                  <strong>{rpResult.unassigned.length} file tanpa bank</strong>: {rpResult.unassigned.map((u) => u.file).join(", ")}.
                  Beri nama file dengan nomor/nama bank, mis. &quot;13. Deutsche ….xlsx&quot;.
                </div>
              )}
              <p className="text-[11px] text-slate-500">
                Item = hari yang menurut bank memenuhi tetapi menurut rekap BI tidak (dari nilai tabel, catatan bank, atau nama file
                bukti yang menyebut tanggal). Hari yang menurut bank justru lebih buruk tidak dijadikan item.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
