export type ThresholdStage = "EARLY" | "INTERMEDIATE" | "END_STATE"
export type RoleMode = "BI" | "BANK_DU"
export type ComplianceStatus = "MEMENUHI" | "PEMBINAAN_DSMM" | "SANKSI_TEGURAN"

export interface MasterBank {
  bank_id: string
  masked_alias: string
  nama_resmi_bank: string
  kelompok_kbmi: string
  kode_bloomberg: string
  kode_sppa_antasena: string
}

export interface ParameterMetricDetail {
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
}

export interface BankScoreMatrixItem {
  bank_id: string
  masked_alias: string
  nama_resmi_bank: string
  kelompok_kbmi: string
  raw_metrics: {
    B1: number
    B2: number
    B3: number
    B4: number
    B5: number
    B6: number
    B7a: number
    B7b: number
    B8: number
    OM1: number
    OM2: number
    OM3: number
    [key: string]: number
  }
  passed_flags: {
    B1: boolean
    B2: boolean
    B3: boolean
    B4: boolean
    B5: boolean
    B6: boolean
    B7a: boolean
    B7b: boolean
    B8: boolean
    OM1: boolean
    OM2: boolean
    OM3: boolean
    [key: string]: boolean
  }
  weighted_scores: {
    B1: number
    B2: number
    B3: number
    B4: number
    B5: number
    B6: number
    B7a: number
    B7b: number
    B8: number
    OM1: number
    OM2: number
    OM3: number
    [key: string]: number
  }
  total_puva_score: number
  total_om_score: number
  composite_score: number
  compliance_status: ComplianceStatus
  detail_metrics?: {
    [paramCode: string]: ParameterMetricDetail
  }
}

export interface FailedTransactionItem {
  tanggal?: string
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
  bi_decision_status: "OPEN" | "PENDING_REVIEW" | "APPROVED" | "REJECTED"
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
  rawRate: number
  isPassed: boolean
  score: number
  weight: number
  threshold: number
  stage: ThresholdStage
  metricDetail?: ParameterMetricDetail
  failedTransactions?: FailedTransactionItem[]
  findingId?: string
}
