"use client"

import React, { createContext, useContext, useState, useEffect, useCallback } from "react"
import {
  ThresholdStage,
  RoleMode,
  MasterBank,
  BankScoreMatrixItem,
  FindingTicketItem,
  DrillDownSelection,
} from "@/types"

interface AppContextType {
  activeMenu: string
  setActiveMenu: (menu: string) => void
  isSidebarCollapsed: boolean
  setIsSidebarCollapsed: (collapsed: boolean) => void
  toggleSidebar: () => void

  selectedPeriod: string
  setSelectedPeriod: (period: string) => void

  selectedStage: ThresholdStage
  changeStage: (stage: ThresholdStage) => Promise<void>

  isMasked: boolean
  setIsMasked: (masked: boolean) => void
  toggleMasked: () => void

  roleMode: RoleMode
  setRoleMode: (mode: RoleMode) => void

  simulatedBankId: string
  setSimulatedBankId: (id: string) => void

  matrix: BankScoreMatrixItem[]
  banks: MasterBank[]
  findings: FindingTicketItem[]
  isLoading: boolean
  isRecalculating: boolean
  refreshData: () => Promise<void>

  // DrillDown Drawer State
  drillDown: DrillDownSelection | null
  openDrillDown: (selection: DrillDownSelection) => void
  closeDrillDown: () => void
  isDrawerOpen: boolean
}

const AppContext = createContext<AppContextType | undefined>(undefined)

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeMenu, setActiveMenu] = useState<string>("matrix")
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false)

  const [selectedPeriod, setSelectedPeriod] = useState<string>("2026-Q2")
  const [selectedStage, setSelectedStage] = useState<ThresholdStage>("EARLY")
  const [isMasked, setIsMasked] = useState<boolean>(true) // Default true: Mode Alias (Bank A - Bank U)
  const [roleMode, setRoleMode] = useState<RoleMode>("BI")
  const [simulatedBankId, setSimulatedBankId] = useState<string>("DU-01")

  const [matrix, setMatrix] = useState<BankScoreMatrixItem[]>([])
  const [banks, setBanks] = useState<MasterBank[]>([])
  const [findings, setFindings] = useState<FindingTicketItem[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [isRecalculating, setIsRecalculating] = useState<boolean>(false)

  // Drawer
  const [drillDown, setDrillDown] = useState<DrillDownSelection | null>(null)
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false)

  const toggleSidebar = () => setIsSidebarCollapsed(prev => !prev)
  const toggleMasked = () => setIsMasked(prev => !prev)

  const openDrillDown = (selection: DrillDownSelection) => {
    setDrillDown(selection)
    setIsDrawerOpen(true)
  }

  const closeDrillDown = () => {
    setIsDrawerOpen(false)
  }

  const fetchData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [matrixRes, banksRes, findingsRes] = await Promise.all([
        fetch(`/api/matrix?stage=${selectedStage}`),
        fetch("/api/banks"),
        fetch("/api/findings"),
      ])

      if (matrixRes.ok) {
        const matrixJson = await matrixRes.json()
        setMatrix(matrixJson)
      }
      if (banksRes.ok) {
        const banksJson = await banksRes.json()
        setBanks(banksJson)
      }
      if (findingsRes.ok) {
        const findingsJson = await findingsRes.json()
        setFindings(findingsJson)
      }
    } catch (err) {
      console.error("Gagal memuat data dari API backend:", err)
    } finally {
      setIsLoading(false)
    }
  }, [selectedStage])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const changeStage = async (stage: ThresholdStage) => {
    if (stage === selectedStage) return
    setIsRecalculating(true)
    try {
      const res = await fetch(`/api/evaluation/recalculate?stage=${stage}`, {
        method: "POST",
      })
      if (res.ok) {
        setSelectedStage(stage)
        const matrixRes = await fetch(`/api/matrix?stage=${stage}`)
        if (matrixRes.ok) {
          const matrixJson = await matrixRes.json()
          setMatrix(matrixJson)
        }
        const findingsRes = await fetch("/api/findings")
        if (findingsRes.ok) {
          const findingsJson = await findingsRes.json()
          setFindings(findingsJson)
        }
      }
    } catch (err) {
      console.error("Gagal mengubah tahap threshold:", err)
    } finally {
      setIsRecalculating(false)
    }
  }

  return (
    <AppContext.Provider
      value={{
        activeMenu,
        setActiveMenu,
        isSidebarCollapsed,
        setIsSidebarCollapsed,
        toggleSidebar,
        selectedPeriod,
        setSelectedPeriod,
        selectedStage,
        changeStage,
        isMasked,
        setIsMasked,
        toggleMasked,
        roleMode,
        setRoleMode,
        simulatedBankId,
        setSimulatedBankId,
        matrix,
        banks,
        findings,
        isLoading,
        isRecalculating,
        refreshData: fetchData,
        drillDown,
        openDrillDown,
        closeDrillDown,
        isDrawerOpen,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

export const useApp = () => {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error("useApp must be used within an AppProvider")
  }
  return context
}
