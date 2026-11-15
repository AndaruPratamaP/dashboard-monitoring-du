"use client"

import React, { useEffect, useState } from "react"
import { useApp } from "@/context/AppContext"
import { Lock, Unlock, Download, FileText, FileSpreadsheet, Archive, RefreshCw, AlertTriangle, Gavel } from "lucide-react"

interface SnapshotStatus {
  period: string
  stage: string
  is_locked: boolean
  locked_at: string | null
  locked_by: string | null
  snapshot_id: string | null
}

interface DocColumn {
  key: string
  group: string
  label: string
  kind: "pct" | "ratio" | "count"
  target: number
  target_after: number
  label_before: string
  label_after: string
}

interface DocRow {
  no: number
  bank_id: string
  nama: string
  cells: Record<string, number | null>
  gagal_sebelum: Record<string, boolean>
  gagal_setelah: Record<string, boolean>
  keterangan: Record<string, string[]>
  penuh: boolean
  lolos_threshold: boolean
}

interface Escalation {
  id: number
  bank: string
  parameter: string
  nama_parameter: string
  tanggal: string
  tenor: string
  nilai_bi: string
  nilai_bank: string
  ronde: string
  keterangan_bank: string
  alasan_penolakan: string
}

interface DocPreview {
  period: { label: string; label_pendek: string; triwulan: string }
  stage_text: string
  is_locked: boolean
  columns: DocColumn[]
  note_columns: { key: string; label: string }[]
  rows: DocRow[]
  stats: Record<string, { mean: number | null; median: number | null }>
  ringkasan: {
    jumlah_bank: number
    penuh: string[]
    belum_penuh: string[]
    lolos_threshold: string[]
    tidak_lolos_threshold: string[]
  }
  sanggahan: { total: number; DITERIMA: number; DITOLAK: number; OPEN: number; eskalasi: number }
  eskalasi: Escalation[]
  memo: { hasil: string; per_bank: string[]; kesimpulan: string; konfirmasi: string | null }
  files: Record<string, string>
}

const GROUP_STYLE: Record<string, string> = {
  "Kuotasi Repo": "bg-[#00B050] text-white",
  "Kuotasi OIS": "bg-[#00B050] text-white",
  "Kuotasi SRBI": "bg-[#00B050] text-white",
  Transaksi: "bg-[#0070C0] text-white",
  "Ctp Line Repo": "bg-[#7030A0] text-white",
  "Ctp Line OIS": "bg-[#7030A0] text-white",
  "Partisipasi Matchmaking OIS": "bg-[#FFC000] text-slate-900",
}

const DOCS: { kind: string; title: string; desc: string; icon: React.ReactNode }[] = [
  { kind: "m02", title: "M.02 Permohonan Persetujuan", desc: "Memo ke pimpinan DPPK", icon: <FileText className="w-4 h-4" /> },
  { kind: "m02-lampiran", title: "Lampiran M.02", desc: "Matriks, keterangan, dan eskalasi", icon: <FileText className="w-4 h-4" /> },
  { kind: "m01", title: "M.01 ke DSMM", desc: "Memo penyampaian hasil evaluasi", icon: <FileText className="w-4 h-4" /> },
  { kind: "m01-lampiran", title: "Lampiran M.01", desc: "Matriks & keterangan", icon: <FileText className="w-4 h-4" /> },
  { kind: "surat", title: "Surat ke Bank DU", desc: "Pengantar workbook konfirmasi", icon: <FileText className="w-4 h-4" /> },
  { kind: "matriks", title: "Matriks Excel", desc: "Sebelum/setelah threshold", icon: <FileSpreadsheet className="w-4 h-4" /> },
]

function fmt(col: DocColumn, v: number | null): string {
  if (v === null || v === undefined) return "-"
  if (col.kind === "count") return String(Math.round(v))
  let r = Math.round(v)
  if (v < col.target && r >= col.target) r = col.target - 1
  return `${r}%`
}

function groupSpans(cols: DocColumn[]): { group: string; span: number }[] {
  const out: { group: string; span: number }[] = []
  cols.forEach((c) => {
    const last = out[out.length - 1]
    if (last && last.group === c.group) last.span += 1
    else out.push({ group: c.group, span: 1 })
  })
  return out
}

const MatrixTable: React.FC<{ doc: DocPreview; after: boolean; name: (r: DocRow) => string }> = ({ doc, after, name }) => {
  const flag = after ? "gagal_setelah" : "gagal_sebelum"
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] border-collapse">
        <thead>
          <tr>
            <th colSpan={2} />
            <th colSpan={doc.columns.length} className="bg-black text-white py-1 font-semibold">
              Periode {doc.period.label_pendek}
            </th>
          </tr>
          <tr>
            <th rowSpan={2} className="bg-[#002060] text-white px-2 border border-slate-300">No</th>
            <th rowSpan={2} className="bg-[#002060] text-white px-2 border border-slate-300 text-left">Bank DU PUVA</th>
            {groupSpans(doc.columns).map((g) => (
              <th key={g.group} colSpan={g.span} className={`${GROUP_STYLE[g.group]} px-2 py-1 border border-slate-300`}>
                {g.group}
              </th>
            ))}
          </tr>
          <tr>
            {doc.columns.map((c) => (
              <th key={c.key} className={`${GROUP_STYLE[c.group]} px-1.5 py-1 border border-slate-300 font-medium whitespace-nowrap`}>
                {c.label && <div>{c.label}</div>}
                <div className="opacity-90">({after ? c.label_after : c.label_before})</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {doc.rows.map((r) => {
            const bad = Object.values(r[flag]).some(Boolean)
            return (
              <tr key={r.bank_id} className="hover:bg-slate-50">
                <td className="px-2 py-0.5 border border-slate-200 text-center">{r.no}</td>
                <td className={`px-2 py-0.5 border border-slate-200 font-medium whitespace-nowrap ${bad ? "bg-rose-100 text-rose-800" : ""}`}>
                  {name(r)}
                </td>
                {doc.columns.map((c) => (
                  <td
                    key={c.key}
                    className={`px-1.5 py-0.5 border border-slate-200 text-right tabular-nums ${
                      r[flag][c.key] ? "bg-rose-100 text-rose-700 font-semibold" : ""
                    }`}
                  >
                    {fmt(c, r.cells[c.key])}
                  </td>
                ))}
              </tr>
            )
          })}
          {(["mean", "median"] as const).map((k) => (
            <tr key={k} className="bg-slate-100 text-slate-600">
              <td colSpan={2} className="px-2 py-0.5 border border-slate-200 text-right font-semibold">
                {k === "mean" ? "Mean" : "Median"}
              </td>
              {doc.columns.map((c) => (
                <td key={c.key} className="px-1.5 py-0.5 border border-slate-200 text-right tabular-nums">
                  {fmt({ ...c, target: Infinity }, doc.stats[c.key]?.[k] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Snapshot evaluasi + dokumen akhir (M.02, M.01, lampiran, surat) dalam format dokumen ril DPPK. */
export const DocGeneratorView: React.FC = () => {
  const { selectedStage, isMasked, banks, refreshData, activePeriod } = useApp()
  const [status, setStatus] = useState<SnapshotStatus | null>(null)
  const [doc, setDoc] = useState<DocPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [locking, setLocking] = useState(false)
  const [after, setAfter] = useState(false)

  const aliasOf = Object.fromEntries(banks.map((b) => [b.bank_id, b.masked_alias]))
  const name = (r: { bank_id: string; nama: string }) => (isMasked ? aliasOf[r.bank_id] || r.nama : r.nama)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, p] = await Promise.all([fetch("/api/snapshot/status"), fetch("/api/documents/preview")])
      if (s.ok) setStatus(await s.json())
      const pj = await p.json()
      if (p.ok) setDoc(pj)
      else {
        setDoc(null)
        setError(pj.detail || "Pratinjau dokumen belum tersedia.")
      }
    } catch {
      setError("Gagal menghubungi server.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedStage, activePeriod?.id])

  const toggleLock = async () => {
    if (!status) return
    setLocking(true)
    const res = status.is_locked
      ? await fetch("/api/snapshot/unlock", { method: "POST" })
      : await fetch("/api/snapshot/lock", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ locked_by: "Tim Evaluasi DPPK" }),
        })
    if (!res.ok) setError((await res.json()).detail || "Gagal mengubah status snapshot.")
    await load()
    await refreshData()
    setLocking(false)
  }

  const s = doc?.ringkasan
  const sg = doc?.sanggahan

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900 tracking-tight">Snapshot & Dokumen Akhir</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Format mengikuti dokumen ril DPPK: M.02 ke pimpinan, M.01 ke DSMM, lampiran matriks & keterangan per tanggal.
          </p>
        </div>
        <button
          onClick={load}
          className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg border border-slate-200"
          title="Muat ulang pratinjau"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Snapshot */}
      {status && (
        <div
          className={`rounded-xl border p-4 flex flex-wrap items-center justify-between gap-3 ${
            status.is_locked ? "bg-emerald-50 border-emerald-300" : "bg-amber-50 border-amber-300"
          }`}
        >
          <div className="text-xs">
            <div className="font-bold text-sm flex items-center gap-2">
              {status.is_locked ? <Lock className="w-4 h-4 text-emerald-700" /> : <Unlock className="w-4 h-4 text-amber-700" />}
              {status.is_locked ? "Snapshot terkunci" : "Snapshot belum dikunci (dokumen bertanda DRAFT)"}
            </div>
            <div className="text-slate-600 mt-1">
              {status.is_locked
                ? `${status.snapshot_id || ""} oleh ${status.locked_by || "-"} pada ${status.locked_at ? new Date(status.locked_at).toLocaleString("id-ID") : "-"}. Data, keputusan sanggahan, dan counterparty tidak dapat diubah.`
                : "Kunci snapshot setelah seluruh keputusan sanggahan selesai agar angka dokumen tidak berubah."}
            </div>
          </div>
          <button
            onClick={toggleLock}
            disabled={locking}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold text-white ${
              status.is_locked ? "bg-slate-700 hover:bg-slate-800" : "bg-emerald-600 hover:bg-emerald-700"
            } disabled:opacity-60`}
          >
            {status.is_locked ? <Unlock className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5" />}
            {status.is_locked ? "Buka Kembali" : "Kunci Snapshot"}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600" />
          {error}
        </div>
      )}

      {doc && s && sg && (
        <>
          {/* Ringkasan */}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              ["Memenuhi 100%", s.penuh.length, "text-emerald-700"],
              ["Belum 100%", s.belum_penuh.length, "text-amber-700"],
              [`Lolos threshold`, s.lolos_threshold.length, "text-emerald-700"],
              ["Tidak lolos threshold", s.tidak_lolos_threshold.length, "text-rose-700"],
              ["Sanggahan diterima / total", `${sg.DITERIMA} / ${sg.total}`, "text-slate-800"],
            ].map(([label, value, cls]) => (
              <div key={label as string} className="bg-white rounded-xl border border-slate-200 p-3">
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className={`text-2xl font-bold ${cls}`}>{value}</div>
              </div>
            ))}
          </div>

          {/* Unduh */}
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <h3 className="font-bold text-sm text-slate-900">Dokumen periode {doc.period.label}</h3>
              <a
                href="/api/documents/paket"
                download
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold"
              >
                <Archive className="w-3.5 h-3.5" /> Unduh Semua (ZIP)
              </a>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {DOCS.map((d) => (
                <a
                  key={d.kind}
                  href={`/api/documents/${d.kind}`}
                  download
                  title={doc.files[d.kind]}
                  className="flex items-center gap-3 p-3 rounded-lg border border-slate-200 hover:border-emerald-400 hover:bg-emerald-50/50"
                >
                  <span className="text-emerald-700">{d.icon}</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-xs font-semibold text-slate-800">{d.title}</span>
                    <span className="block text-[11px] text-slate-500 truncate">{d.desc}</span>
                  </span>
                  <Download className="w-3.5 h-3.5 text-slate-400" />
                </a>
              ))}
            </div>
            {!doc.is_locked && (
              <p className="text-[11px] text-amber-700 mt-2">Snapshot belum dikunci: setiap dokumen diberi tanda DRAFT di header.</p>
            )}
          </div>

          {/* Inti memo */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 text-xs text-slate-700 space-y-2 leading-relaxed">
            <h3 className="font-bold text-sm text-slate-900">Isi pokok M.02</h3>
            <p>{doc.memo.hasil}</p>
            {doc.memo.per_bank.length > 0 && (
              <ol className="list-[lower-alpha] pl-6 space-y-0.5">
                {doc.memo.per_bank.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ol>
            )}
            {doc.memo.konfirmasi && <p>{doc.memo.konfirmasi}</p>}
            <p className="font-medium text-slate-900">{doc.memo.kesimpulan}</p>
          </div>

          {/* Matriks lampiran */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-bold text-sm text-slate-900">Lampiran: hasil evaluasi {after ? "setelah" : "sebelum"} penerapan threshold</h3>
              <div className="flex bg-slate-100 p-1 rounded-lg text-xs">
                {[false, true].map((v) => (
                  <button
                    key={String(v)}
                    onClick={() => setAfter(v)}
                    className={`px-3 py-1 rounded-md ${after === v ? "bg-white shadow-xs font-semibold text-slate-900" : "text-slate-600"}`}
                  >
                    {v ? `Setelah threshold (${doc.stage_text})` : "Sebelum threshold"}
                  </button>
                ))}
              </div>
            </div>
            <MatrixTable doc={doc} after={after} name={name} />
          </div>

          {/* Keterangan */}
          <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
            <h3 className="font-bold text-sm text-slate-900">Keterangan Hasil Evaluasi</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] border-collapse">
                <thead>
                  <tr className="bg-[#002060] text-white">
                    <th className="p-1.5 border border-slate-300 w-8">No</th>
                    <th className="p-1.5 border border-slate-300 w-24 text-left">Bank</th>
                    {doc.note_columns.map((c) => (
                      <th key={c.key} className="p-1.5 border border-slate-300">
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {doc.rows
                    .filter((r) => Object.values(r.keterangan).some((v) => v.length))
                    .map((r, i) => (
                      <tr key={r.bank_id} className="align-top">
                        <td className="p-1.5 border border-slate-200 text-center">{i + 1}</td>
                        <td className="p-1.5 border border-slate-200 font-medium">{name(r)}</td>
                        {doc.note_columns.map((c) => (
                          <td key={c.key} className="p-1.5 border border-slate-200 whitespace-pre-line">
                            {(r.keterangan[c.key] || []).join("\n")}
                          </td>
                        ))}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p className="text-[11px] text-slate-500 italic">Hari/tanggal yang sanggahannya diterima telah dihitung memenuhi.</p>
          </div>

          {/* Eskalasi */}
          {doc.eskalasi.length > 0 && (
            <div className="bg-white rounded-xl border border-rose-200 p-4 space-y-3">
              <h3 className="font-bold text-sm text-rose-800 flex items-center gap-2">
                <Gavel className="w-4 h-4" /> Lampiran II M.02: sanggahan yang memerlukan keputusan pimpinan ({doc.eskalasi.length})
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px] border-collapse">
                  <thead className="bg-rose-50 text-rose-900">
                    <tr>
                      {["Bank", "Parameter", "Tanggal", "Tenor", "Rekap BI", "Klaim bank", "Ronde", "Keterangan bank", "Alasan penolakan"].map((h) => (
                        <th key={h} className="p-1.5 border border-rose-100 text-left">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {doc.eskalasi.map((e) => (
                      <tr key={e.id} className="align-top">
                        <td className="p-1.5 border border-slate-200 font-medium">{e.bank}</td>
                        <td className="p-1.5 border border-slate-200">{e.parameter} – {e.nama_parameter}</td>
                        <td className="p-1.5 border border-slate-200 whitespace-nowrap">{e.tanggal}</td>
                        <td className="p-1.5 border border-slate-200">{e.tenor}</td>
                        <td className="p-1.5 border border-slate-200">{e.nilai_bi}</td>
                        <td className="p-1.5 border border-slate-200">{e.nilai_bank}</td>
                        <td className="p-1.5 border border-slate-200">{e.ronde}</td>
                        <td className="p-1.5 border border-slate-200 max-w-xs">{e.keterangan_bank}</td>
                        <td className="p-1.5 border border-slate-200">{e.alasan_penolakan}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
