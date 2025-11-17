import { createContext, useContext, useMemo, useState } from 'react';

const AnalysisContext = createContext(null);

export function AnalysisProvider({ children }) {
  const [analysisRequest, setAnalysisRequest] = useState(null);

  const value = useMemo(
    () => ({
      analysisRequest,
      setAnalysisRequest,
    }),
    [analysisRequest],
  );

  return (
    <AnalysisContext.Provider value={value}>
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const context = useContext(AnalysisContext);
  if (!context) {
    throw new Error('useAnalysis must be used within an AnalysisProvider');
  }
  return context;
}

