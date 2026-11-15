"use client"

import React, { useState } from "react"

interface SheetMap {
  sheet: string
  jenis: string | null
  catatan: string
  manual?: boolean
}

interface Reply {
  id: number
  bank_id: string
  file: string
  kind: string
  summary: { sheet: SheetMap[]; pemetaan_manual?: Record<string, string> } | null
}

const AUTO = ""

/** Pemetaan sheet manual untuk satu workbook balasan (nama sheet tidak dikenali / salah dikenali). */
export const ReplySheetMapper: React.FC<{ bankId: string; file: string; onSaved?: () => void }> = ({ bankId, file, onSaved }) => {
  const [open, setOpen] = useState(false)
  const [reply, setReply] = useState<Reply | null>(null)
  const [kinds, setKinds] = useState<{ key: string; label: string }[]>([])
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const load = async () => {
    const [r, k] = await Promise.all([fetch("/api/replies"), fetch("/api/replies/sheet-kinds")])
    const all: Reply[] = r.ok ? await r.json() : []
    const mine = all.filter((x) => x.bank_id === bankId && x.file === file && x.kind === "WORKBOOK").pop() || null
    setReply(mine)
    if (k.ok) setKinds(await k.json())
    setChoice(mine?.summary?.pemetaan_manual || {})
  }

  const toggle = async () => {
    if (!open) await load()
    setOpen(!open)
    setMsg(null)
  }

  const save = async () => {
    if (!reply) return
    setSaving(true)
    const form = new FormData()
    form.append("mapping", JSON.stringify(Object.fromEntries(Object.entries(choice).filter(([, v]) => v))))
    const res = await fetch(`/api/replies/${reply.id}/mapping`, { method: "POST", body: form })
    const json = await res.json()
    if (res.ok) {
      setMsg(`Diproses ulang: ${json.item.baru} item baru, ${json.item.diperbarui} diperbarui, ${json.item.dihapus} dihapus.`)
      await load()
      onSaved?.()
    } else setMsg(json.detail || "Gagal menyimpan pemetaan.")
    setSaving(false)
  }

  return (
    <span className="ml-1">
      <button onClick={toggle} className="text-emerald-700 hover:underline text-[11px]">
        {open ? "tutup" : "atur sheet"}
      </button>
      {open && (
        <div className="mt-1 p-2 rounded border border-slate-200 bg-slate-50 space-y-1">
          {!reply?.summary && <div className="text-slate-500">Workbook ini belum tercatat sebagai balasan.</div>}
          {reply?.summary?.sheet.map((s) => (
            <div key={s.sheet} className="flex items-center gap-2">
              <span className="font-mono truncate w-48" title={s.sheet}>
                {s.sheet}
              </span>
              <select
                value={choice[s.sheet] ?? AUTO}
                onChange={(e) => setChoice({ ...choice, [s.sheet]: e.target.value })}
                className="border border-slate-300 rounded px-1 py-0.5 text-[11px]"
              >
                <option value={AUTO}>(otomatis)</option>
                {kinds.map((k) => (
                  <option key={k.key} value={k.key}>
                    {k.label}
                  </option>
                ))}
              </select>
              <span className={`text-[11px] ${s.catatan.startsWith("dibaca") ? "text-emerald-700" : "text-slate-400"}`}>{s.catatan}</span>
            </div>
          ))}
          {reply?.summary && (
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={save}
                disabled={saving}
                className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-semibold disabled:opacity-60"
              >
                {saving ? "Memproses…" : "Simpan & proses ulang"}
              </button>
              {msg && <span className="text-[11px] text-slate-600">{msg}</span>}
            </div>
          )}
        </div>
      )}
    </span>
  )
}
