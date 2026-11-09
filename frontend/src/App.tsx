import { BrowserRouter, Route, Routes } from "react-router-dom"

import { AnalysisProvider } from "@/lib/analysis-store"
import { CollectionPage } from "@/pages/collection-page"
import { OnboardingPage } from "@/pages/onboarding-page"
import { OnboardingV2Page } from "@/pages/onboarding-v2-page"
import { OnboardingV3Page } from "@/pages/onboarding-v3-page"
import { PrivacyPage } from "@/pages/privacy-page"
import { StreamPage } from "@/pages/stream-page"

export function App() {
  return (
    <AnalysisProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<OnboardingV3Page />} />
          <Route path="/onboarding-v2" element={<OnboardingV2Page />} />
          <Route path="/onboarding-v1" element={<OnboardingPage />} />
          <Route path="/stream" element={<StreamPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          {/* 기획·운영용 수집 대시보드 (제품 플로우 밖) */}
          <Route path="/collection" element={<CollectionPage />} />
        </Routes>
      </BrowserRouter>
    </AnalysisProvider>
  )
}

export default App
