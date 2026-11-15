export type ThresholdStage = "EARLY" | "INTERMEDIATE" | "END_STATE"
export type ComplianceStatus = "MEMENUHI" | "TIDAK_MEMENUHI" | "DATA_BELUM_LENGKAP"

export const PUVA_CODES = ["B1", "B2", "B3", "B4", "B5", "B6", "B7a", "B7b", "B8"] as const
export type PuvaCode = (typeof PUVA_CODES)[number]

export interface EvaluationPeriodInfo {
  id: number
  tahun: number
  triwulan: string
  active_threshold_stage: ThresholdStage
  is_active: boolean
  is_snapshot_locked: boolean
  working_days_count: number
  mm_ois_sessions_count: number
}

export interface MasterBank {
  bank_id: string
  masked_alias: string
  nama_resmi_bank: string
  kelompok_kbmi: string
  nama_singkat?: string
  sandi_bi?: string
  kode_bbg?: string
  no_urut_konfirmasi?: number
  kode_bloomberg: string
  kode_sppa_antasena: string
}

export interface ParameterMetricDetail {
  sanggahan_diterima?: number
  rate_sebelum_sanggahan?: number | null
  sensitivitas_batas?: Array<{ tenor: string; batas_dipakai_bps: number; batas_alternatif_bps: number; hari_terdampak: Array<{ tanggal: string; spread_bps: number }>; rate_jika_alternatif: number; catatan: string }>
  counterparty_setelah_cutoff?: string[]
  valid_days?: number
  total_days?: number
  rate?: number
  line_du?: number
  line_non_du?: number
  target_du?: number
  target_non_du?: number
  win_perdana?: number
  target_sales?: number
  actual_sales?: number
  target_days?: number
  valid_sessions?: number
  total_sessions?: number
  rasio_penjualan_pct?: number | null
}

export interface BankScoreMatrixItem {
  bank_id: string
  masked_alias: string
  nama_resmi_bank: string
  nama_singkat?: string
  kelompok_kbmi: string
  period?: string
  /** null = sumber data parameter belum diunggah */
  raw_metrics: Record<string, number | null>
  /** null = belum ada data */
  passed_flags: Record<string, boolean | null>
  weighted_scores: Record<string, number | null>
  total_puva_score: number
  max_puva_score?: number
  compliance_status: ComplianceStatus
  detail_metrics?: {
    [paramCode: string]: ParameterMetricDetail
  }
}

export interface FailedTransactionItem {
  tanggal?: string
  tenor_tidak_dikuotasi?: string[]
  rasio_penjualan?: string
  platform?: string
  tenor?: string
  seri?: string
  deal_id?: string
  bid_rate?: number
  ask_rate?: number
  spread_bps?: number
  max_allowed_bps?: number
  tenor_hari?: number
  min_allowed_tenor?: number
  volume_miliar_rp?: number
  realisasi_line_du?: number
  realisasi_line_non_du?: number
  target_line_du?: number
  target_line_non_du?: number
  volume_win_perdana?: number
  target_kewajiban_30pct?: number
  realisasi_penjualan_sekunder?: number
  persentase_terhadap_win?: string
  kekurangan_volume?: number
  rasio_pemenuhan?: string
  // Format data ril (Sprint 2)
  rincian?: Array<{ tenor: string; spread_bps: number | null; batas_bps?: number; masalah: string }>
  hari_bertransaksi?: number
  target_hari?: number
  total_hari_kerja?: number
  tanggal_tanpa_transaksi?: string[]
  volume_win_perdana_miliar?: number
  target_kewajiban_30pct_miliar?: number
  realisasi_penjualan_sekunder_miliar?: number
  alasan?: string
  parameter?: string
  peran?: string
}

export interface FindingTicketItem {
  finding_id: string
  bank_id: string
  masked_alias: string
  nama_resmi_bank: string
  parameter_code: string
  nilai_rekap_bi: string
  detail_transaksi_gugur: FailedTransactionItem[]
  nilai_klaim_bank: string | null
  alasan_sanggahan: string | null
  file_bukti_name: string | null
  ai_recommendation_status: "RECOMMEND_APPROVE" | "RECOMMEND_REJECT" | "PARTIAL_REVIEW" | null
  ai_analysis_text: string | null
  bi_decision_status: "OPEN" | "PENDING_REVIEW" | "APPROVED" | "REJECTED" | "CLOSED"
  verified_by: string | null
  updated_at: string
}

export interface DrillDownSelection {
  bankId: string
  bankAlias: string
  bankOfficialName: string
  kbmi: string
  paramCode: string
  paramName: string
  paramDetail: string
  rawRate: number | null
  isPassed: boolean | null
  score: number
  weight: number
  threshold: number
  stage: ThresholdStage
  metricDetail?: ParameterMetricDetail
  failedTransactions?: FailedTransactionItem[]
  findingId?: string
}
