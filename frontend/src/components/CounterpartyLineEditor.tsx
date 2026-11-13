"use client"

import React, { useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"

interface Line {
  id: number
  instrument: "REPO" | "OIS"
  sandi: string
  nama: string
  status: string | null
  is_du: boolean
  dihapus: boolean
  setelah_cutoff: boolean
  source_file: string
  dikonfirmasi_bank: boolean
}

/** Koreksi status counterparty line satu bank oleh petugas BI; B4/B5 dihitung ulang setiap perubahan. */
export const CounterpartyLineEditor: React.FC<{
  bankId: string
  onChanged: (breakdown: Record<string, any>) => void
}> = ({ bankId, onChanged }) => {
  const [lines, setLines] = useState<Line[] | null>(null)
  const [saving, setSaving] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    const res = await fetch(`/api/counterparty/${bankId}`)
    if (res.ok) setLines(await res.json())
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bankId])

  if (!lines) return <RefreshCw className="w-4 h-4 animate-spin text-slate-400 m-2" />

  // Pilihan status mengikuti label cut-off pada data (mis. "Sebelum 30 Juni 2026")
  const found = lines.map((l) => l.status || "").join(" ").match(/(\d{1,2}\s+[A-Za-z]+\s+\d{4})/)
  const cutoff = found ? found[1] : ""
  const options = cutoff ? [`Sebelum ${cutoff}`, `Setelah ${cutoff}`, "Dihapus"] : ["Sebelum cut-off", "Setelah cut-off", "Dihapus"]

  const save = async (line: Line, status: string) => {
    setSaving(line.id)
    setError(null)
    const form = new FormData()
    form.append("status", status)
    const res = await fetch(`/api/counterparty/lines/${line.id}`, { method: "PATCH", body: form })
    const json = await res.json()
    if (!res.ok) setError(json.detail || "Gagal menyimpan koreksi.")
    else onChanged(json.breakdown)
    await load()
    setSaving(null)
  }

  return (
    <div className="grid md:grid-cols-2 gap-3 p-2 bg-slate-50 rounded-lg">
      {error && <div className="md:col-span-2 text-rose-700">{error}</div>}
      {(["REPO", "OIS"] as const).map((inst) => {
        const rows = lines.filter((l) => l.instrument === inst)
        return (
          <div key={inst}>
            <div className="font-semibold text-slate-700 mb-1">
              Line {inst === "REPO" ? "Repo" : "OIS"} ({rows.filter((r) => !r.dihapus).length} aktif)
            </div>
            <div className="max-h-72 overflow-y-auto rounded border border-slate-200 bg-white">
              <table className="w-full text-[11px]">
                <tbody className="divide-y divide-slate-100">
                  {rows.map((l) => (
                    <tr key={l.id} className={l.dihapus ? "text-slate-400 line-through" : ""}>
                      <td className="p-1.5">
                        <span className="no-underline">{l.nama}</span>
                        {l.is_du && <span className="ml-1 px-1 rounded bg-emerald-100 text-emerald-800 no-underline">DU</span>}
                        {l.setelah_cutoff && (
                          <span className="ml-1 px-1 rounded bg-sky-100 text-sky-800" title="Dibuka setelah cut-off; tetap dihitung">
                            baru
                          </span>
                        )}
                      </td>
                      <td className="p-1.5 w-40">
                        <select
                          value={options.includes(l.status || "") ? l.status || "" : ""}
                          onChange={(e) => save(l, e.target.value)}
                          disabled={saving === l.id}
                          className="w-full px-1 py-0.5 border border-slate-300 rounded"
                        >
                          {!options.includes(l.status || "") && <option value="">{l.status || "(kosong)"}</option>}
                          {options.map((o) => (
                            <option key={o} value={o}>
                              {o}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      })}
    </div>
  )
}
