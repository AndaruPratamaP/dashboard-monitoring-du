"use client"

import React, { useEffect, useState } from "react"
import { useApp } from "@/context/AppContext"
import { RealDataIngestPanel } from "@/components/RealDataIngestPanel"
import { ShieldCheck, History, RefreshCw } from "lucide-react"

interface UploadRow {
  id: number
  kind: "SUMBER" | "COUNTERPARTY" | "BALASAN"
  source: string | null
  file: string
  sha256: string
  ukuran: number | null
  asal: "UNGGAH" | "LOKAL"
  oleh: string
  waktu: string | null
  catatan: string | null
}

const KIND_LABEL: Record<UploadRow["kind"], string> = {
  SUMBER: "File sumber",
  COUNTERPARTY: "Counterparty",
  BALASAN: "Balasan bank",
}

/** Riwayat file yang diproses beserta SHA-256 (jejak setiap angka ke file & versi sumbernya). */
const UploadHistoryCard: React.FC = () => {
  const { activePeriod } = useApp()
  const [rows, setRows] = useState<UploadRow[]>([])
  const [kind, setKind] = useState<string>("")
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    const res = await fetch(`/api/uploads${kind ? `?kind=${kind}` : ""}`)
    if (res.ok) setRows(await res.json())
    setLoading(false)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, activePeriod?.id])

  // Versi berubah: hash berbeda dari pemrosesan sebelumnya untuk file bernama sama
  const changed = new Set<number>()
  const lastHash: Record<string, string> = {}
  ;[...rows].reverse().forEach((r) => {
    const key = `${r.kind}|${r.source}|${r.file}`
    if (lastHash[key] && lastHash[key] !== r.sha256) changed.add(r.id)
    lastHash[key] = r.sha256
  })

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
      <div className="p-4 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center space-x-2">
          <History className="w-4 h-4 text-emerald-600" />
          <h3 className="font-bold text-xs text-slate-800 uppercase tracking-wider">Riwayat File Diproses</h3>
          <span className="text-[11px] text-slate-500 normal-case">SHA-256 setiap file yang dipakai menghitung matriks</span>
        </div>
        <div className="flex items-center gap-2">
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="text-xs border border-slate-300 rounded px-2 py-1">
            <option value="">Semua</option>
            <option value="SUMBER">File sumber</option>
            <option value="COUNTERPARTY">Counterparty</option>
            <option value="BALASAN">Balasan bank</option>
          </select>
          <button onClick={load} className="p-1 text-slate-500 hover:text-slate-800" title="Muat ulang">
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="w-full text-left text-xs border-collapse">
          <thead className="bg-slate-100 text-slate-700 font-semibold sticky top-0">
            <tr>
              <th className="p-2">Waktu (UTC)</th>
              <th className="p-2">Jenis</th>
              <th className="p-2">Sumber/Bank</th>
              <th className="p-2">File</th>
              <th className="p-2">SHA-256</th>
              <th className="p-2">Asal</th>
              <th className="p-2">Catatan</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="p-4 text-center text-slate-400">
                  Belum ada file yang diproses pada periode ini.
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="p-2 whitespace-nowrap text-slate-500">{r.waktu?.replace("T", " ")}</td>
                <td className="p-2">{KIND_LABEL[r.kind]}</td>
                <td className="p-2 font-mono text-[11px]">{r.source || "-"}</td>
                <td className="p-2 max-w-xs truncate" title={r.file}>
                  {r.file}
                  {changed.has(r.id) && (
                    <span className="ml-1 px-1 rounded bg-amber-100 text-amber-800 text-[10px]" title="Isi file berbeda dari pemrosesan sebelumnya">
                      versi baru
                    </span>
                  )}
                </td>
                <td className="p-2 font-mono text-[11px] text-slate-500" title={r.sha256}>
                  {r.sha256.slice(0, 12)}…
                </td>
                <td className="p-2">{r.asal === "UNGGAH" ? "Unggahan" : "Folder lokal"}</td>
                <td className="p-2 text-slate-500">{r.catatan}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export const SmartEtlView: React.FC = () => {
  const { banks } = useApp()

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900 tracking-tight">Data Sumber & Entity Resolution</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          File kerja DPPK diproses per sumber; triwulan ditentukan dari tanggal di dalam file.
        </p>
      </div>

      <RealDataIngestPanel />

      <UploadHistoryCard />

      {/* Entity Resolution Reference Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="p-4 bg-slate-50 border-b border-slate-200 flex items-center space-x-2">
          <ShieldCheck className="w-4 h-4 text-emerald-600" />
          <h3 className="font-bold text-xs text-slate-800 uppercase tracking-wider">Tabel Master Entity Resolution</h3>
        </div>
        <div className="overflow-x-auto max-h-72">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-100 text-slate-700 font-semibold sticky top-0 border-b border-slate-200">
              <tr>
                <th className="p-2.5 w-20">Bank ID</th>
                <th className="p-2.5 w-28">Masked Alias</th>
                <th className="p-2.5">Nama Resmi Bank</th>
                <th className="p-2.5 w-24">Kelompok</th>
                <th className="p-2.5 w-24 font-mono">Sandi BI</th>
                <th className="p-2.5 w-28 font-mono">Kode BBG</th>
                <th className="p-2.5 w-24 font-mono">No. Konfirmasi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-medium">
              {banks.map((b) => (
                <tr key={b.bank_id} className="hover:bg-slate-50 transition-colors">
                  <td className="p-2.5 font-bold font-mono text-emerald-700">{b.bank_id}</td>
                  <td className="p-2.5 font-semibold text-slate-800">{b.masked_alias}</td>
                  <td className="p-2.5 text-slate-700">{b.nama_resmi_bank}</td>
                  <td className="p-2.5 text-slate-500">{b.kelompok_kbmi}</td>
                  <td className="p-2.5 font-mono text-[11px] text-amber-700 bg-amber-50/40">{b.sandi_bi}</td>
                  <td className="p-2.5 font-mono text-[11px] text-blue-600 bg-blue-50/40">{b.kode_bbg}</td>
                  <td className="p-2.5 font-mono text-[11px] text-slate-600">{b.no_urut_konfirmasi}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
