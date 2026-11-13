"use client"

import React, { useCallback, useEffect, useMemo, useState } from "react"
import { useApp } from "@/context/AppContext"
import {
  AlertTriangle,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  FileText,
  History,
  Paperclip,
  Plus,
  RefreshCw,
  RotateCcw,
  Scale,
  ShieldCheck,
  X,
} from "lucide-react"

interface Precheck {
  label: "MINTA_BUKTI" | "VERIFIKASI_BUKTI"
  engine: string
  points: string[]
}

interface DisputeItem {
  id: number
  tanggal: string | null
  tenor: string | null
  tenor_label: string | null
  nilai_bi: string | null
  nilai_bank: string | null
  keterangan_bank: string | null
  source_file: string | null
  round_no: number
  last_round: number
  status: "OPEN" | "DITERIMA" | "DITOLAK"
  decided_by: string | null
  decision_note: string | null
  decided_at: string | null
  history: Array<{ at: string; ronde: number; event: string; oleh: string; catatan: string | null }>
  precheck: Precheck
  perlu_keputusan_pimpinan: boolean
}

interface DisputeGroup {
  bank_id: string
  nama_singkat: string
  masked_alias: string
  parameter_code: string
  source: string
  label: string
  threshold: number
  rate_rekap_bi: number | null
  rate_sekarang: number | null
  rate_jika_semua_diterima: number | null
  status_parameter: boolean | null
  bukti: Array<{ id: number; file: string }>
  items: DisputeItem[]
  jumlah: { OPEN: number; DITERIMA: number; DITOLAK: number }
}

interface Round {
  round_no: number
  opened_at: string | null
  deadline: string | null
  note: string | null
}

const STATUS_STYLE: Record<string, string> = {
  OPEN: "bg-amber-50 text-amber-800 border-amber-200",
  DITERIMA: "bg-emerald-50 text-emerald-800 border-emerald-200",
  DITOLAK: "bg-rose-50 text-rose-800 border-rose-200",
}

const TICKET_STYLE: Record<string, string> = {
  OPEN: "bg-amber-50 text-amber-800",
  PENDING_REVIEW: "bg-blue-50 text-blue-800",
  APPROVED: "bg-emerald-50 text-emerald-800",
  REJECTED: "bg-rose-50 text-rose-800",
  CLOSED: "bg-slate-100 text-slate-600",
}

const MANUAL_SOURCES = [
  { key: "bbg-repo", label: "B1 Kuotasi Repo", tenors: ["on", "1w", "1m"] },
  { key: "bbg-srbi", label: "B2 Kuotasi SRBI", tenors: ["any"] },
  { key: "bbg-ois", label: "B3 Kuotasi OIS", tenors: ["3b", "12b"] },
  { key: "repo-2m", label: "B7a Transaksi Repo", tenors: [] },
  { key: "srbi-3b", label: "B7b Transaksi SRBI", tenors: [] },
  { key: "mm-ois", label: "B8 Partisipasi MM OIS", tenors: ["1b", "3b"] },
]

const pct = (v: number | null) => (v === null || v === undefined ? "—" : `${v.toFixed(2)}%`)
const fmtDate = (d: string | null) =>
  d ? new Date(d + "T00:00:00").toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" }) : "agregat"

export const ReconciliationView: React.FC = () => {
  const { findings, isMasked, refreshData, banks } = useApp() as any
  const [tab, setTab] = useState<"items" | "tickets">("items")
  const [groups, setGroups] = useState<DisputeGroup[]>([])
  const [round, setRound] = useState<Round | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<string>("")
  const [filter, setFilter] = useState<"OPEN" | "ALL" | "ESKALASI">("OPEN")
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [busyItem, setBusyItem] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ id: number; file: string } | null>(null)
  const [openHistory, setOpenHistory] = useState<number | null>(null)
  const [roundForm, setRoundForm] = useState(false)
  const [deadline, setDeadline] = useState("")
  const [manualOpen, setManualOpen] = useState(false)
  const [manual, setManual] = useState({ bank_id: "", source: "bbg-repo", tanggal: "", tenor: "", keterangan: "" })
  const [manualMsg, setManualMsg] = useState<string | null>(null)

  const bankName = (g: { masked_alias: string; nama_singkat: string }) => (isMasked ? g.masked_alias : g.nama_singkat)
  const keyOf = (g: DisputeGroup) => `${g.bank_id}|${g.source}`

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/disputes")
      if (res.ok) {
        const json = await res.json()
        setGroups(json.groups)
        setRound(json.round)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const visible = useMemo(
    () =>
      groups.filter((g) =>
        filter === "ALL" ? true : filter === "OPEN" ? g.jumlah.OPEN > 0 : g.items.some((i) => i.perlu_keputusan_pimpinan),
      ),
    [groups, filter],
  )

  useEffect(() => {
    // Grup yang sedang dibuka tetap terpilih walau keluar dari filter setelah diputus
    if (visible.length && !groups.some((g) => keyOf(g) === selected)) setSelected(keyOf(visible[0]))
  }, [visible, groups, selected])

  const group = groups.find((g) => keyOf(g) === selected) || null
  const totals = useMemo(
    () => ({
      open: groups.reduce((a, g) => a + g.jumlah.OPEN, 0),
      diterima: groups.reduce((a, g) => a + g.jumlah.DITERIMA, 0),
      ditolak: groups.reduce((a, g) => a + g.jumlah.DITOLAK, 0),
      eskalasi: groups.reduce((a, g) => a + g.items.filter((i) => i.perlu_keputusan_pimpinan).length, 0),
    }),
    [groups],
  )

  const decide = async (item: DisputeItem, decision: "DITERIMA" | "DITOLAK" | "OPEN") => {
    setBusyItem(item.id)
    setError(null)
    try {
      const form = new FormData()
      form.append("decision", decision)
      if (notes[item.id]) form.append("note", notes[item.id])
      const res = await fetch(`/api/disputes/${item.id}/decide`, { method: "POST", body: form })
      const json = await res.json()
      if (!res.ok) setError(json.detail || "Keputusan gagal disimpan.")
      await load()
      await refreshData()
    } catch {
      setError("Server backend tidak dapat dihubungi.")
    } finally {
      setBusyItem(null)
    }
  }

  const openRound = async () => {
    const form = new FormData()
    if (deadline) form.append("deadline", deadline)
    const res = await fetch("/api/rounds", { method: "POST", body: form })
    const json = await res.json()
    if (!res.ok) setError(json.detail || "Gagal membuka ronde baru.")
    setRoundForm(false)
    setDeadline("")
    await load()
  }

  const submitManual = async () => {
    setManualMsg(null)
    const form = new FormData()
    Object.entries(manual).forEach(([k, v]) => v && form.append(k, v))
    const res = await fetch("/api/disputes/manual", { method: "POST", body: form })
    const json = await res.json()
    if (!res.ok) {
      setManualMsg(json.detail || "Gagal mencatat sanggahan.")
      return
    }
    setManualMsg(`${json.baru} item baru dicatat.`)
    setManual({ ...manual, tanggal: "", keterangan: "" })
    await load()
  }

  const manualTenors = MANUAL_SOURCES.find((s) => s.key === manual.source)?.tenors || []

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
            <Scale className="w-5 h-5 text-emerald-600" /> Rekonsiliasi Sanggahan
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Selisih isian balasan bank vs rekap BI per tanggal. Keputusan petugas langsung menghitung ulang parameter.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-200">
            <CalendarClock className="w-4 h-4 text-slate-500" />
            {round ? (
              <span>
                <strong>Ronde {round.round_no}</strong>
                {round.deadline ? ` · tenggat ${fmtDate(round.deadline)}` : " · tanpa tenggat"}
              </span>
            ) : (
              <span className="text-slate-500">Belum ada ronde (dibuat saat impor balasan)</span>
            )}
          </div>
          {roundForm ? (
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
                className="px-2 py-1.5 border border-slate-300 rounded-lg text-xs"
                title="Tenggat balasan bank"
              />
              <button onClick={openRound} className="px-2.5 py-1.5 bg-slate-900 text-white rounded-lg font-semibold">
                Buka
              </button>
              <button onClick={() => setRoundForm(false)} className="px-2 py-1.5 text-slate-500">
                Batal
              </button>
            </div>
          ) : (
            <button
              onClick={() => setRoundForm(true)}
              title="Mulai ronde baru setelah tanggapan BI dikirim ulang ke bank"
              className="flex items-center gap-1 px-3 py-1.5 border border-slate-300 hover:bg-slate-50 rounded-lg font-semibold text-slate-700"
            >
              <Plus className="w-3.5 h-3.5" /> Ronde Baru
            </button>
          )}
        </div>
      </div>

      {/* Ringkasan */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        {[
          { label: "Menunggu keputusan", v: totals.open, cls: "text-amber-700" },
          { label: "Diterima", v: totals.diterima, cls: "text-emerald-700" },
          { label: "Ditolak", v: totals.ditolak, cls: "text-rose-700" },
          { label: "Perlu keputusan pimpinan", v: totals.eskalasi, cls: "text-purple-700" },
        ].map((c) => (
          <div key={c.label} className="p-3 bg-white rounded-xl border border-slate-200">
            <div className="text-slate-500">{c.label}</div>
            <div className={`text-2xl font-black ${c.cls}`}>{c.v}</div>
          </div>
        ))}
      </div>

      {/* Tab */}
      <div className="flex gap-1 border-b border-slate-200 text-xs font-semibold">
        {[
          { id: "items", label: "Sanggahan per tanggal" },
          { id: "tickets", label: `Tiket temuan (${findings.length})` },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id as any)}
            className={`px-3 py-2 border-b-2 -mb-px ${tab === t.id ? "border-emerald-600 text-emerald-700" : "border-transparent text-slate-500"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="flex items-start gap-2 p-2.5 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-800">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {tab === "tickets" ? (
        <TicketTable findings={findings} isMasked={isMasked} />
      ) : loading ? (
        <div className="py-16 text-center text-slate-400 text-xs">
          <RefreshCw className="w-5 h-5 animate-spin inline" />
        </div>
      ) : groups.length === 0 ? (
        <div className="p-8 bg-white border border-dashed border-slate-300 rounded-xl text-center text-sm text-slate-500">
          Belum ada sanggahan. Impor balasan bank di <strong>Smart ETL &amp; Data Hub → Konfirmasi Bank</strong>.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Daftar bank-parameter */}
          <div className="lg:col-span-4 space-y-2">
            <div className="flex gap-1 text-[11px] font-semibold">
              {(["OPEN", "ESKALASI", "ALL"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-2.5 py-1 rounded-full border ${filter === f ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-600 border-slate-200"}`}
                >
                  {f === "OPEN" ? "Belum diputus" : f === "ESKALASI" ? "Eskalasi" : "Semua"}
                </button>
              ))}
            </div>
            {visible.length === 0 && <div className="text-xs text-slate-400 p-3">Tidak ada item pada filter ini.</div>}
            {visible.map((g) => {
              const passNow = g.rate_sekarang !== null && g.rate_sekarang >= g.threshold
              return (
                <button
                  key={keyOf(g)}
                  onClick={() => {
                    setSelected(keyOf(g))
                    setPreview(null)
                  }}
                  className={`w-full text-left p-3 rounded-xl border text-xs transition-colors ${
                    keyOf(g) === selected ? "bg-emerald-50/60 border-emerald-300" : "bg-white border-slate-200 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-slate-900">{bankName(g)}</span>
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{g.parameter_code}</span>
                  </div>
                  <div className="text-slate-500 mt-0.5">{g.label}</div>
                  <div className="flex items-center gap-2 mt-1.5 text-[11px]">
                    <span className={`font-semibold ${passNow ? "text-emerald-700" : "text-rose-700"}`}>{pct(g.rate_sekarang)}</span>
                    <span className="text-slate-400">ambang {g.threshold}%</span>
                    <span className="ml-auto flex gap-1">
                      {g.jumlah.OPEN > 0 && <span className="px-1.5 rounded bg-amber-100 text-amber-800">{g.jumlah.OPEN} open</span>}
                      {g.jumlah.DITERIMA > 0 && <span className="px-1.5 rounded bg-emerald-100 text-emerald-800">{g.jumlah.DITERIMA} ✓</span>}
                      {g.jumlah.DITOLAK > 0 && <span className="px-1.5 rounded bg-rose-100 text-rose-800">{g.jumlah.DITOLAK} ✗</span>}
                    </span>
                  </div>
                </button>
              )
            })}

            {/* Sanggahan manual */}
            <div className="p-3 bg-white rounded-xl border border-slate-200 text-xs">
              <button onClick={() => setManualOpen(!manualOpen)} className="flex items-center gap-1 font-semibold text-slate-700">
                {manualOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                Catat sanggahan manual
              </button>
              {manualOpen && (
                <div className="mt-2 space-y-2">
                  <p className="text-[11px] text-slate-500">
                    Untuk sanggahan lewat surat/email atau file yang tidak terbaca otomatis (mis. ber-password).
                  </p>
                  <select
                    value={manual.bank_id}
                    onChange={(e) => setManual({ ...manual, bank_id: e.target.value })}
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg"
                  >
                    <option value="">Pilih bank…</option>
                    {(banks || []).map((b: any) => (
                      <option key={b.bank_id} value={b.bank_id}>
                        {isMasked ? b.masked_alias : b.nama_singkat || b.nama_resmi_bank}
                      </option>
                    ))}
                  </select>
                  <div className="flex gap-2">
                    <select
                      value={manual.source}
                      onChange={(e) => setManual({ ...manual, source: e.target.value, tenor: "" })}
                      className="flex-1 px-2 py-1.5 border border-slate-300 rounded-lg"
                    >
                      {MANUAL_SOURCES.map((s) => (
                        <option key={s.key} value={s.key}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    {manualTenors.length > 0 && (
                      <select
                        value={manual.tenor}
                        onChange={(e) => setManual({ ...manual, tenor: e.target.value })}
                        className="w-24 px-2 py-1.5 border border-slate-300 rounded-lg"
                      >
                        <option value="">semua</option>
                        {manualTenors.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  <input
                    type="date"
                    value={manual.tanggal}
                    onChange={(e) => setManual({ ...manual, tanggal: e.target.value })}
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg"
                  />
                  <textarea
                    value={manual.keterangan}
                    onChange={(e) => setManual({ ...manual, keterangan: e.target.value })}
                    placeholder="Alasan/bukti dari bank (mis. surat no. …, screenshot terlampir di email)"
                    rows={2}
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg"
                  />
                  <button
                    onClick={submitManual}
                    disabled={!manual.bank_id || !manual.tanggal || !manual.keterangan}
                    className="px-3 py-1.5 bg-slate-900 text-white rounded-lg font-semibold disabled:opacity-40"
                  >
                    Catat
                  </button>
                  {manualMsg && <div className="text-[11px] text-slate-600">{manualMsg}</div>}
                </div>
              )}
            </div>
          </div>

          {/* Detail */}
          <div className="lg:col-span-8 space-y-4">
            {group && (
              <>
                <div className="p-4 bg-white rounded-xl border border-slate-200">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="text-[11px] font-mono text-slate-500">
                        {group.parameter_code} · {group.label}
                      </div>
                      <h3 className="text-base font-extrabold text-slate-900">{bankName(group)}</h3>
                    </div>
                    <div className="flex items-center gap-2 text-xs">
                      {[
                        { l: "Rekap BI", v: group.rate_rekap_bi },
                        { l: "Saat ini", v: group.rate_sekarang },
                        { l: "Jika semua diterima", v: group.rate_jika_semua_diterima },
                      ].map((x, i) => (
                        <div key={x.l} className="flex items-center gap-2">
                          {i > 0 && <span className="text-slate-300">→</span>}
                          <div className="text-center">
                            <div className="text-[10px] text-slate-500">{x.l}</div>
                            <div
                              className={`font-black text-sm ${
                                x.v !== null && x.v >= group.threshold ? "text-emerald-700" : "text-rose-700"
                              }`}
                            >
                              {pct(x.v)}
                            </div>
                          </div>
                        </div>
                      ))}
                      <div className="text-[10px] text-slate-400 pl-2 border-l border-slate-200">ambang {group.threshold}%</div>
                    </div>
                  </div>

                  {group.bukti.length > 0 && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]">
                      <Paperclip className="w-3.5 h-3.5 text-slate-500" />
                      <span className="text-slate-500">Bukti dari bank:</span>
                      {group.bukti.map((b) => (
                        <button
                          key={b.id}
                          onClick={() => setPreview(preview?.id === b.id ? null : b)}
                          className={`flex items-center gap-1 px-2 py-0.5 rounded border font-mono ${
                            preview?.id === b.id ? "bg-slate-900 text-white border-slate-900" : "bg-slate-50 border-slate-200 text-slate-700"
                          }`}
                        >
                          <Eye className="w-3 h-3" /> {b.file}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {preview && (
                  <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 border-b border-slate-100 text-xs">
                      <span className="font-mono text-slate-700 flex items-center gap-1">
                        <FileText className="w-3.5 h-3.5" /> {preview.file}
                      </span>
                      <div className="flex items-center gap-2">
                        <a href={`/api/replies/${preview.id}/file`} target="_blank" rel="noreferrer" className="text-emerald-700 font-semibold">
                          Buka di tab baru
                        </a>
                        <button onClick={() => setPreview(null)} className="text-slate-400 hover:text-slate-700">
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                    {/\.(png|jpe?g)$/i.test(preview.file) ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={`/api/replies/${preview.id}/file`} alt={preview.file} className="max-h-[480px] mx-auto" />
                    ) : (
                      <iframe src={`/api/replies/${preview.id}/file`} title={preview.file} className="w-full h-[480px]" />
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  {group.items.map((it) => (
                    <div key={it.id} className="p-3.5 bg-white rounded-xl border border-slate-200 text-xs space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-slate-900">{fmtDate(it.tanggal)}</span>
                        {it.tenor_label && <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{it.tenor_label}</span>}
                        <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${STATUS_STYLE[it.status]}`}>{it.status}</span>
                        {it.perlu_keputusan_pimpinan && (
                          <span className="px-2 py-0.5 rounded-full bg-purple-50 text-purple-800 border border-purple-200 text-[10px] font-bold">
                            Perlu keputusan pimpinan
                          </span>
                        )}
                        <span className="text-[10px] text-slate-400 ml-auto">
                          ronde {it.round_no}
                          {it.last_round > it.round_no ? `–${it.last_round}` : ""} · {it.source_file}
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="p-2 rounded-lg bg-rose-50/60 border border-rose-100">
                          <div className="text-[10px] text-rose-700 font-semibold">Rekap BI</div>
                          <div className="font-semibold text-slate-800">{it.nilai_bi}</div>
                        </div>
                        <div className="p-2 rounded-lg bg-emerald-50/60 border border-emerald-100">
                          <div className="text-[10px] text-emerald-700 font-semibold">Isian / klaim bank</div>
                          <div className="font-semibold text-slate-800">{it.nilai_bank}</div>
                        </div>
                      </div>
                      {it.keterangan_bank && (
                        <div className="text-slate-600">
                          <span className="font-semibold text-slate-700">Keterangan bank: </span>
                          {it.keterangan_bank}
                        </div>
                      )}
                      <div className="p-2 rounded-lg bg-slate-50 border border-slate-200">
                        <div className="flex items-center gap-1 text-[10px] font-bold text-slate-600 mb-1">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> Pre-check PADG ·{" "}
                          <span className={it.precheck.label === "MINTA_BUKTI" ? "text-amber-700" : "text-slate-700"}>
                            {it.precheck.label === "MINTA_BUKTI" ? "minta bukti" : "verifikasi bukti"}
                          </span>
                        </div>
                        <ul className="list-disc pl-4 space-y-0.5 text-slate-600">
                          {it.precheck.points.map((p, i) => (
                            <li key={i}>{p}</li>
                          ))}
                        </ul>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {it.status === "OPEN" ? (
                          <>
                            <input
                              value={notes[it.id] || ""}
                              onChange={(e) => setNotes({ ...notes, [it.id]: e.target.value })}
                              placeholder="Catatan keputusan (opsional)"
                              className="flex-1 min-w-[12rem] px-2 py-1.5 border border-slate-300 rounded-lg"
                            />
                            <button
                              onClick={() => decide(it, "DITERIMA")}
                              disabled={busyItem === it.id}
                              className="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg font-semibold disabled:opacity-50"
                            >
                              <Check className="w-3.5 h-3.5" /> Terima
                            </button>
                            <button
                              onClick={() => decide(it, "DITOLAK")}
                              disabled={busyItem === it.id}
                              className="flex items-center gap-1 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg font-semibold disabled:opacity-50"
                            >
                              <X className="w-3.5 h-3.5" /> Tolak
                            </button>
                          </>
                        ) : (
                          <>
                            <span className="text-slate-500">
                              {it.status === "DITERIMA" ? "Diterima" : "Ditolak"} oleh {it.decided_by}
                              {it.decision_note ? ` — "${it.decision_note}"` : ""}
                            </span>
                            <button
                              onClick={() => decide(it, "OPEN")}
                              disabled={busyItem === it.id}
                              className="flex items-center gap-1 px-2 py-1 border border-slate-300 rounded-lg text-slate-600 hover:bg-slate-50 ml-auto"
                            >
                              <RotateCcw className="w-3 h-3" /> Batalkan
                            </button>
                          </>
                        )}
                        <button
                          onClick={() => setOpenHistory(openHistory === it.id ? null : it.id)}
                          className="flex items-center gap-1 px-2 py-1 text-slate-500 hover:text-slate-800"
                        >
                          <History className="w-3.5 h-3.5" /> Riwayat ({it.history.length})
                        </button>
                      </div>
                      {openHistory === it.id && (
                        <ol className="border-l-2 border-slate-200 pl-3 space-y-1 text-[11px] text-slate-600">
                          {it.history.map((h, i) => (
                            <li key={i}>
                              <span className="font-mono text-slate-400">{h.at.replace("T", " ")}</span> · ronde {h.ronde} ·{" "}
                              <strong>{h.event}</strong> oleh {h.oleh}
                              {h.catatan ? ` — ${h.catatan}` : ""}
                            </li>
                          ))}
                        </ol>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const TicketTable: React.FC<{ findings: any[]; isMasked: boolean }> = ({ findings, isMasked }) => {
  if (!findings.length)
    return <div className="p-8 text-center text-sm text-slate-500 bg-white rounded-xl border border-slate-200">Tidak ada tiket temuan.</div>
  return (
    <div className="overflow-x-auto bg-white rounded-xl border border-slate-200">
      <table className="w-full text-xs text-left">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="p-2.5">Tiket</th>
            <th className="p-2.5">Bank</th>
            <th className="p-2.5">Parameter</th>
            <th className="p-2.5">Nilai rekap</th>
            <th className="p-2.5">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {findings.map((t) => (
            <tr key={t.finding_id}>
              <td className="p-2.5 font-mono text-slate-500">{t.finding_id}</td>
              <td className="p-2.5 font-semibold text-slate-800">{isMasked ? t.masked_alias : t.nama_resmi_bank}</td>
              <td className="p-2.5">{t.parameter_code}</td>
              <td className="p-2.5 text-slate-600">{t.nilai_rekap_bi}</td>
              <td className="p-2.5">
                <span className={`px-2 py-0.5 rounded-full font-bold text-[10px] ${TICKET_STYLE[t.bi_decision_status] || ""}`}>
                  {t.bi_decision_status === "CLOSED" ? "DITUTUP (lolos)" : t.bi_decision_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="p-2.5 text-[11px] text-slate-400 border-t border-slate-100">
        Tiket dibuat otomatis untuk parameter di bawah ambang dan ditutup otomatis bila parameter lolos setelah sanggahan diterima,
        rekalkulasi, atau ganti tahap.
      </p>
    </div>
  )
}
