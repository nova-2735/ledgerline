import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { isAccessError } from '@/api/hooks'
import { AppShell, restoreAccessCode } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Dashboard } from '@/pages/Dashboard'
import { Inbox } from '@/pages/Inbox'

function Placeholder({ title }: { title: string }) {
  return <div className="panel p-6"><h1 className="page-title">{title}</h1><p className="mt-2 text-muted-foreground">Coming in next block</p></div>
}

export default function App() {
  const [queryClient] = useState(() => {
    restoreAccessCode()
    return new QueryClient({ defaultOptions: { queries: {
      retry: (count, error) => count < 1 && !isAccessError(error),
    } } })
  })
  return <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="inbox" element={<Inbox />} />
            <Route path="runs/:id" element={<Placeholder title="Invoice run" />} />
            <Route path="queue" element={<Placeholder title="Review queue" />} />
            <Route path="purchase-orders" element={<Placeholder title="Purchase orders" />} />
            <Route path="purchase-orders/:po" element={<Placeholder title="Purchase order" />} />
            <Route path="vendors" element={<Placeholder title="Vendors" />} />
            <Route path="policy" element={<Placeholder title="Policy" />} />
            <Route path="*" element={<div className="panel p-6"><h1 className="page-title">Page not found</h1><Link to="/" className="mt-2 inline-block text-indigo-700 hover:underline">Go to dashboard</Link></div>} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </TooltipProvider>
  </QueryClientProvider>
}
