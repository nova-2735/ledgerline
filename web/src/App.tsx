import { lazy, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { isAccessError } from '@/api/hooks'
import { AppShell, restoreAccessCode } from '@/components/layout/AppShell'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
const Dashboard = lazy(() => import('@/pages/Dashboard').then(module => ({ default: module.Dashboard })))
const Inbox = lazy(() => import('@/pages/Inbox').then(module => ({ default: module.Inbox })))
const Runs = lazy(() => import('@/pages/Runs').then(module => ({ default: module.Runs })))
const RunView = lazy(() => import('@/pages/RunView').then(module => ({ default: module.RunView })))
const Policy = lazy(() => import('@/pages/Policy').then(module => ({ default: module.Policy })))
const PoDetail = lazy(() => import('@/pages/PoDetail').then(module => ({ default: module.PoDetail })))
const PurchaseOrders = lazy(() => import('@/pages/PurchaseOrders').then(module => ({ default: module.PurchaseOrders })))
const Queue = lazy(() => import('@/pages/Queue').then(module => ({ default: module.Queue })))
const Vendors = lazy(() => import('@/pages/Vendors').then(module => ({ default: module.Vendors })))

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
            <Route path="runs" element={<Runs />} />
            <Route path="runs/:id" element={<RunView />} />
            <Route path="queue" element={<Queue />} />
            <Route path="purchase-orders" element={<PurchaseOrders />} />
            <Route path="purchase-orders/:po" element={<PoDetail />} />
            <Route path="vendors" element={<Vendors />} />
            <Route path="policy" element={<Policy />} />
            <Route path="*" element={<div className="panel p-6"><h1 className="page-title">Page not found</h1><Link to="/" className="mt-2 inline-block text-indigo-700 hover:underline">Go to dashboard</Link></div>} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster position="bottom-right" />
    </TooltipProvider>
  </QueryClientProvider>
}
