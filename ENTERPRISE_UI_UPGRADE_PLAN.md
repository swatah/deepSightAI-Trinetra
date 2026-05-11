# Enterprise-Grade UI Upgrade Plan for deepSightAI Trinetra

## Current State Analysis

### Existing UI (Streamlit)
- **Technology**: Streamlit single-page app (`UI/ui.py`)
- **Deployment**: Manual Python script execution (no containerization)
- **Configuration**: Hardcoded IP addresses (must edit before use)
- **Features**: Basic video upload, RTSP, text search (query API at port 8081 not implemented)
- **Authentication**: None
- **Multi-tenancy**: None
- **Observability**: None
- **Deployment**: No Docker/K8s support for UI itself

### Critical Gaps
1. No Docker container for UI
2. No Kubernetes manifests
3. No authentication/authorization integration
4. Hardcoded configuration (not 12-factor app)
5. No health checks or monitoring
6. Not responsive/production-ready (Streamlit default styling)
7. No tenant isolation
8. No audit logging from UI actions
9. No rate limiting or quota display
10. No CI/CD pipeline for UI

---

## Target State: Enterprise UI

### Architecture Goals
- Containerized (Docker + Kubernetes)
- Cloud-native (12-factor app compliant)
- Secure (auth, TLS, RBAC)
- Observable (metrics, logs, tracing)
- Multi-tenant aware
- Sector-specific UI variants
- Responsive design (mobile/desktop)
- CI/CD automated deployment
- Self-service configuration

---

## Phase 1: UI Technology Assessment & Decisions (Week 1-2)

### 1.1 Technology Choice Analysis

**Current**: Streamlit
- ✅ Quick prototyping
- ✅ Python-only (no JS/TS)
- ❌ Limited customization
- ❌ Poor enterprise features
- ❌ Limited auth integration
- ❌ Not easily containerizable for enterprise scale

**Option A**: Keep Streamlit but upgrade
- Keep existing codebase
- Add custom components for auth
- Deploy in container
- Limited flexibility

**Option B**: Migrate to Streamlit Cloud alternatives
- Gradio? (similar limitations)
- Keep Python focus

**Option C**: Modern React/Next.js frontend (RECOMMENDED)
- ✅ Full control over UI/UX
- ✅ Industry standard
- ✅ Rich ecosystem (auth libraries, observability, etc.)
- ✅ Better performance
- ✅ TypeScript support
- ✅ API Gateway integration ready
- ❌ Requires JS/TS expertise
- ❌ More complex build pipeline

**Decision**: **Option C** - Build React/Next.js frontend with modular architecture

### 1.2 UI Architecture Design

```
┌─────────────────────────────────────────────────────────┐
│                     Load Balancer (Ingress)              │
│                    TLS Termination                       │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  API Gateway (Kong/Traefik)              │
│  - Auth (JWT validation)                                │
│  - Rate limiting per tenant                             │
│  - Request routing to UI backend                        │
└──────────────────────────┬──────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
        ▼                                     ▼
┌─────────────────┐                 ┌──────────────────┐
│  UI Backend     │                 │  Static Assets   │
│  (Next.js API   │                 │  (CDN/CloudFront)│
│   Routes)       │                 │  or S3           │
└─────────────────┘                 └──────────────────┘
        │
        ▼
┌─────────────────────────────────────────────┐
│          UI Components (React/TSX)           │
│  - Auth (Login/Logout)                      │
│  - Dashboard (tenant-specific)              │
│  - Video Upload (with quota display)        │
│  - RTSP Management                          │
│  - Search Interface (text/image)            │
│  - Results Grid (with timestamps)           │
│  - Scene Detection (optional)               │
│  - Analytics (usage metrics)                │
│  - Admin Panel (tenant/users if applicable) │
│  - Sector-specific panels (LE/Commercial)   │
└─────────────────────────────────────────────┘
```

---

## Phase 2: UI Implementation Plan (Months 1-3)

### 2.1 Project Setup (Week 1-2)

**Create new UI project structure**:
```
ui-frontend/
├── src/
│   ├── app/                    # Next.js 14+ App Router
│   │   ├── (auth)/            # Auth group routes (login, logout)
│   │   ├── dashboard/         # Main dashboard
│   │   ├── upload/            # Video upload page
│   │   ├── search/            # Search interface
│   │   ├── results/           # Results display
│   │   ├── admin/             # Admin panel (if tenant admin)
│   │   ├── analytics/         # Usage analytics
│   │   └── layout.tsx         # Root layout
│   ├── components/            # Reusable UI components
│   │   ├── ui/               # ShadCN/ui components
│   │   ├── VideoUploader.tsx
│   │   ├── SearchBox.tsx
│   │   ├── ResultsGrid.tsx
│   │   ├── FrameCard.tsx
│   │   ├── RTSPAdd.tsx
│   │   ├── QuotaMeter.tsx
│   │   └── TenantSwitcher.tsx (if multi-tenant admin)
│   ├── lib/                  # Utility libraries
│   │   ├── api.ts            # API client with auth
│   │   ├── auth.ts           # Auth helpers (JWT)
│   │   ├── tenant.ts         # Tenant context
│   │   └── utils.ts
│   ├── types/                # TypeScript definitions
│   │   ├── api.ts
│   │   ├── tenant.ts
│   │   └── video.ts
│   └── middleware.ts         # Next.js middleware (auth check)
├── public/                   # Static assets
│   ├── logo.svg
│   └── favicon.ico
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.prod
│   └── nginx.conf (if needed)
├── k8s/
│   ├── base/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   └── hpa.yaml
│   └── overlays/
│       ├── development/
│       └── production/
├── helm/
│   └── ui-frontend/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
├── .env.example
├── .env.local (gitignored)
├── next.config.js
├── tailwind.config.js
├── tsconfig.json
├── package.json
├── Dockerfile
└── README.md
```

**Tech Stack**:
- **Framework**: Next.js 14+ (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS + ShadCN/ui components
- **State Management**: Zustand or React Context (simple)
- **API Client**: Axios or Fetch with interceptors
- **Auth**: NextAuth.js or Clerk/Auth0 integration
- **Forms**: React Hook Form + Zod validation
- **Icons**: Lucide React
- **Charts**: Recharts (for analytics)
- **Image Display**: Next/Image optimized
- **Error Tracking**: Sentry
- **Analytics**: PostHog or Mixpanel (optional)

### 2.2 Docker & K8s Configuration (Week 3)

**Dockerfile**:
```dockerfile
# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM node:18-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
```

**K8s Deployment**:
```yaml
# k8s/base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ui-frontend
  namespace: deepSightAI-Trinetra-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ui-frontend
  template:
    metadata:
      labels:
        app: ui-frontend
    spec:
      containers:
      - name: ui-frontend
        image: deepSightAI-Trinetra/ui-frontend:latest
        ports:
        - containerPort: 3000
        envFrom:
        - configMapRef:
            name: ui-frontend-config
        - secretRef:
            name: ui-frontend-secrets
        resources:
          requests:
            memory: "256Mi"
            cpu: "200m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /
            port: 3000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /
            port: 3000
          initialDelaySeconds: 5
          periodSeconds: 5
---
# k8s/base/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: ui-frontend
  namespace: deepSightAI-Trinetra-platform
spec:
  selector:
    app: ui-frontend
  ports:
  - port: 80
    targetPort: 3000
  type: ClusterIP
---
# k8s/base/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ui-frontend-hpa
  namespace: deepSightAI-Trinetra-platform
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ui-frontend
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

**Kustomize overlay** (`k8s/overlays/production/kustomization.yaml`):
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: deepSightAI-Trinetra-platform

bases:
- ../../base

patchesStrategicMerge:
- ./patches/ingress.yaml
- ./patches/resources.yaml

configMapGenerator:
- name: ui-frontend-config
  behavior: merge
  literals:
  - NEXT_PUBLIC_API_URL=https://api.deepSightai.com
  - NEXT_PUBLIC_QUERY_API_URL=https://query.deepSightai.com
  - NEXT_PUBLIC_ENVIRONMENT=production
  - NEXT_PUBLIC_SENTRY_DSN=${SENTRY_DSN}
```

### 2.3 Multi-Tenant UI (Week 4-6)

**Tenant Context Provider**:
```typescript
// src/contexts/TenantContext.tsx
'use client'

import { createContext, useContext, useState, useEffect } from 'react'
import { useSession } from 'next-auth/react'

interface Tenant {
  id: string
  name: string
  sector: 'law_enforcement' | 'commercial' | 'logistics'
  plan: 'starter' | 'professional' | 'enterprise'
  quotas: {
    videosPerMonth: number
    storageGB: number
    searchQPS: number
    retentionDays: number
  }
}

interface TenantContextType {
  tenant: Tenant | null
  setTenant: (tenant: Tenant) => void
  canUpload: boolean
  usage: {
    videosUploaded: number
    storageUsed: number
    searchesPerformed: number
  }
}

const TenantContext = createContext<TenantContextType | undefined>(undefined)

export function TenantProvider({ children }: { children: React.ReactNode }) {
  const { data: session } = useSession()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [usage, setUsage] = useState({ videosUploaded: 0, storageUsed: 0, searchesPerformed: 0 })

  useEffect(() => {
    if (session?.user?.tenantId) {
      // Fetch tenant details and usage
      fetchTenant(session.user.tenantId).then(setTenant)
      fetchUsage(session.user.tenantId).then(setUsage)
    }
  }, [session])

  const canUpload = tenant && usage.videosUploaded < tenant.quotas.videosPerMonth

  return (
    <TenantContext.Provider value={{ tenant, setTenant, canUpload, usage }}>
      {children}
    </TenantContext.Provider>
  )
}

export const useTenant = () => {
  const context = useContext(TenantContext)
  if (!context) throw new Error('useTenant must be used within TenantProvider')
  return context
}
```

**Sector-specific UI Components**:
```typescript
// src/components/SectorBadge.tsx
'use client'

import { Badge } from '@/components/ui/badge'
import { useTenant } from '@/contexts/TenantContext'

export function SectorBadge() {
  const { tenant } = useTenant()
  
  if (!tenant) return null
  
  const sectorConfig = {
    law_enforcement: { label: 'Law Enforcement', variant: 'destructive' as const, icon: Shield },
    commercial: { label: 'Commercial', variant: 'default' as const, icon: Store },
    logistics: { label: 'Logistics', variant: 'outline' as const, icon: Truck },
  }
  
  const config = sectorConfig[tenant.sector]
  
  return (
    <Badge variant={config.variant} className="gap-1">
      <config.icon className="h-3 w-3" />
      {config.label}
    </Badge>
  )
}
```

### 2.4 Authentication Integration (Week 7-8)

**Integration with Auth Service**:
```typescript
// src/app/api/auth/[...nextauth]/route.ts
import NextAuth from 'next-auth'
import KeycloakProvider from 'next-auth/providers/keycloak'

const handler = NextAuth({
  providers: [
    KeycloakProvider({
      clientId: process.env.KEYCLOAK_CLIENT_ID,
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET,
      issuer: process.env.KEYCLOAK_ISSUER,
    }),
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      if (account && user) {
        token.tenantId = user.tenant_id
        token.roles = user.roles
      }
      return token
    },
    async session({ session, token }) {
      session.user.tenantId = token.tenantId as string
      session.user.roles = token.roles as string[]
      return session
    },
  },
})

export { handler as GET, handler as POST }
```

**Protected Route Middleware**:
```typescript
// src/middleware.ts
import { withAuth } from 'next-auth/middleware'

export default withAuth({
  pages: {
    signIn: '/auth/login',
  },
  callbacks: {
    authorized: ({ token, req }) => {
      // Check tenant access
      const tenantId = token.tenantId as string
      const path = req.nextUrl.pathname

      // Allow tenant-specific routes
      if (path.startsWith(`/tenant/${tenantId}`)) {
        return true
      }

      // Admin routes require role check
      if (path.startsWith('/admin')) {
        return (token.roles as string[])?.includes('admin')
      }

      return !!token
    },
  },
})
```

### 2.5 Enhanced UI Features (Week 9-12)

**Video Upload with Quota Display**:
```tsx
// src/components/VideoUploader.tsx
'use client'

import { useState } from 'react'
import { useTenant } from '@/contexts/TenantContext'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Upload, AlertCircle } from 'lucide-react'

export function VideoUploader() {
  const { tenant, usage, canUpload } = useTenant()
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)

  const handleUpload = async (file: File) => {
    if (!canUpload) {
      alert(`Upload limit reached. Upgrade your plan.`)
      return
    }

    setUploading(true)
    const formData = new FormData()
    formData.append('video', file)

    // Upload with progress tracking
    await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    })
    
    setUploading(false)
    setProgress(100)
  }

  return (
    <div className="space-y-4">
      {tenant && (
        <div className="text-sm text-muted-foreground">
          <div>Videos this month: {usage.videosUploaded} / {tenant.quotas.videosPerMonth}</div>
          <Progress value={(usage.videosUploaded / tenant.quotas.videosPerMonth) * 100} />
        </div>
      )}

      {!canUpload && (
        <div className="flex items-center gap-2 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <AlertCircle className="h-4 w-4 text-yellow-600" />
          <span className="text-sm text-yellow-800">
            You've reached your monthly upload limit. Contact your admin to upgrade.
          </span>
        </div>
      )}

      <div className="border-2 border-dashed rounded-lg p-8 text-center">
        <input
          type="file"
          accept="video/*"
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          disabled={!canUpload || uploading}
          className="hidden"
          id="video-upload"
        />
        <label htmlFor="video-upload" className="cursor-pointer">
          <Upload className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="mt-2">Click to upload video (MP4)</p>
          <p className="text-sm text-muted-foreground">Max {tenant?.quotas.videosPerMonth} videos/month</p>
        </label>
      </div>
    </div>
  )
}
```

**Search Interface**:
```tsx
// src/app/search/page.tsx
'use client'

import { SearchBox } from '@/components/SearchBox'
import { ResultsGrid } from '@/components/ResultsGrid'
import { useSearch } from '@/hooks/useSearch'
import { SectorFilter } from '@/components/SectorFilter' // For LE: weapon detection, etc.

export default function SearchPage() {
  const { results, search, loading } = useSearch()

  return (
    <div className="container mx-auto py-8">
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold">Search Video Frames</h1>
          <SectorFilter /> // Dynamic based on tenant.sector
        </div>
        
        <SearchBox onSearch={search} disabled={loading} />
        
        {loading && <p>Searching...</p>}
        
        {results && (
          <div className="mt-8">
            <p className="text-sm text-muted-foreground mb-4">
              Found {results.length} results
            </p>
            <ResultsGrid results={results} />
          </div>
        )}
      </div>
    </div>
  )
}
```

### 2.6 Analytics Dashboard (Week 13-14)

```tsx
// src/app/analytics/page.tsx
'use client'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { useTenant } from '@/contexts/TenantContext'

export default function AnalyticsPage() {
  const { usage, tenant } = useTenant()

  // Mock data - replace with real API
  const videoStats = [
    { day: 'Mon', uploads: 4 },
    { day: 'Tue', uploads: 7 },
    { day: 'Wed', uploads: 3 },
    { day: 'Thu', uploads: 6 },
    { day: 'Fri', uploads: 8 },
    { day: 'Sat', uploads: 2 },
    { day: 'Sun', uploads: 1 },
  ]

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-3xl font-bold mb-8">Usage Analytics</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <Card>
          <CardHeader>
            <CardTitle>Videos Uploaded</CardTitle>
            <CardDescription>This month</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold">{usage.videosUploaded} / {tenant?.quotas.videosPerMonth}</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Storage Used</CardTitle>
            <CardDescription>GB</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold">{usage.storageUsed.toFixed(1)} GB</p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Search Queries</CardTitle>
            <CardDescription>This month</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-4xl font-bold">{usage.searchesPerformed}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Upload Activity</CardTitle>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={videoStats}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="uploads" fill="#1976D2" />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  )
}
```

---

## Phase 3: CI/CD & GitOps (Week 15-16)

### 3.1 GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: UI CI/CD

on:
  push:
    branches: [main, develop]
    paths: ['ui-frontend/**']
  pull_request:
    branches: [main]
    paths: ['ui-frontend/**']

jobs:
  lint:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ui-frontend
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
          cache-dependency-path: ui-frontend/package-lock.json
      - name: Install dependencies
        run: npm ci
      - name: Run linter
        run: npm run lint
      - name: Type check
        run: npm run type-check
      - name: Run tests
        run: npm test

  build:
    needs: lint
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ui-frontend
    steps:
      - uses: actions/checkout@v4
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'
          cache-dependency-path: ui-frontend/package-lock.json
      - name: Install dependencies
        run: npm ci
      - name: Build
        run: npm run build
      - name: Run tests
        run: npm test
      - name: Upload build artifacts
        uses: actions/upload-artifact@v4
        with:
          name: ui-build
          path: ui-frontend/.next

  docker-build:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      - name: Log in to container registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: ./ui-frontend
          push: true
          tags: |
            ghcr.io/swatah/deepSightAI-Trinetra/ui-frontend:${{ github.sha }}
            ghcr.io/swatah/deepSightAI-Trinetra/ui-frontend:latest
          cache-from: type=registry,ref=ghcr.io/swatah/deepSightAI-Trinetra/ui-frontend:latest
          cache-to: type=inline

  deploy:
    needs: docker-build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to development via ArgoCD
        if: github.ref == 'refs/heads/develop'
        run: |
          argocd app set-image ui-frontend-dev ui-frontend=ghcr.io/swatah/deepSightAI-Trinetra/ui-frontend:${{ github.sha }}
          argocd app sync ui-frontend-dev
        env:
          ARGOCD_SERVER: ${{ secrets.ARGOCD_SERVER_DEV }}
          ARGOCD_USERNAME: ${{ secrets.ARGOCD_USERNAME }}
          ARGOCD_PASSWORD: ${{ secrets.ARGOCD_PASSWORD }}
      
      - name: Deploy to production via ArgoCD
        if: github.ref == 'refs/heads/main'
        run: |
          argocd app set-image ui-frontend-prod ui-frontend=ghcr.io/swatah/deepSightAI-Trinetra/ui-frontend:${{ github.sha }}
          argocd app sync ui-frontend-prod --prune
        env:
          ARGOCD_SERVER: ${{ secrets.ARGOCD_SERVER_PROD }}
          ARGOCD_USERNAME: ${{ secrets.ARGOCD_USERNAME }}
          ARGOCD_PASSWORD: ${{ secrets.ARGOCD_PASSWORD }}
```

---

## Phase 4: Observability (Week 17)

### 4.1 Monitoring Stack

**Integrate with existing Prometheus/Grafana**:

```typescript
// src/lib/metrics.ts
import { Counter, Histogram } from 'prom-client'

export const uiMetrics = {
  pageViews: new Counter({
    name: 'ui_page_views_total',
    help: 'Total page views',
    labelNames: ['page', 'tenant'],
  }),
  apiCalls: new Counter({
    name: 'ui_api_calls_total',
    help: 'Total API calls from UI',
    labelNames: ['endpoint', 'method', 'status', 'tenant'],
  }),
  searchLatency: new Histogram({
    name: 'ui_search_latency_seconds',
    help: 'Search request latency',
    labelNames: ['tenant'],
    buckets: [0.1, 0.5, 1, 2, 5],
  }),
  uploadErrors: new Counter({
    name: 'ui_upload_errors_total',
    help: 'Upload errors',
    labelNames: ['error_type', 'tenant'],
  }),
}

// Instrument API calls
export function instrumentedFetch(url: string, options?: RequestInit) {
  const start = Date.now()
  
  return fetch(url, options).then(async (response) => {
    const duration = (Date.now() - start) / 1000
    uiMetrics.apiCalls.inc({
      endpoint: url,
      method: options?.method || 'GET',
      status: response.status.toString(),
      tenant: getCurrentTenantId(),
    })
    return response
  })
}
```

**Metrics endpoint** (`src/app/api/metrics/route.ts`):
```typescript
import { NextResponse } from 'next/server'
import { register } from 'prom-client'

export async function GET() {
  try {
    const metrics = await register.metrics()
    return new NextResponse(metrics, {
      headers: { 'Content-Type': register.contentType },
    })
  } catch (error) {
    return new NextResponse('Error generating metrics', { status: 500 })
  }
}
```

### 4.2 Error Tracking (Sentry)

```typescript
// src/lib/sentry.ts
import * as Sentry from '@sentry/nextjs'

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  tracesSampleRate: 1.0,
  replaysSessionSampleRate: 0.1,
  environment: process.env.NEXT_PUBLIC_ENVIRONMENT,
  beforeSend(event) {
    // Add tenant info to errors
    if (event.user) {
      event.user = {
        ...event.user,
        tenant_id: getCurrentTenantId(),
      }
    }
    return event
  },
})
```

---

## Phase 5: Testing & Quality (Week 18-19)

### 5.1 Testing Strategy

**Unit Tests** (Jest + React Testing Library):
```typescript
// src/__tests__/VideoUploader.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { VideoUploader } from '@/components/VideoUploader'
import { TenantProvider } from '@/contexts/TenantContext'

const mockTenant = {
  id: 'test-tenant',
  quotas: { videosPerMonth: 10 },
}

describe('VideoUploader', () => {
  it('shows upload limit when quota exceeded', () => {
    render(
      <TenantProvider value={{ tenant: mockTenant, usage: { videosUploaded: 10 }, setTenant: () => {} }}>
        <VideoUploader />
      </TenantProvider>
    )
    
    expect(screen.getByText(/upload limit reached/i)).toBeInTheDocument()
  })
})
```

**E2E Tests** (Playwright):
```typescript
// e2e/auth.spec.ts
import { test, expect } from '@playwright/test'

test('admin can login and see dashboard', async ({ page }) => {
  await page.goto('/auth/login')
  await page.fill('[name="username"]', 'admin@test.com')
  await page.fill('[name="password"]', 'password')
  await page.click('button[type="submit"]')
  
  await expect(page).toHaveURL('/dashboard')
  await expect(page.locator('text=Usage Analytics')).toBeVisible()
})
```

### 5.2 Performance Optimization

- **Code splitting**: Dynamic imports for heavy components
- **Image optimization**: Next/Image with proper sizing
- **Caching**: CDN for static assets, Redis for API responses
- **Bundle analysis**: `@next/bundle-analyzer`
- **Lazy loading**: For non-critical components

---

## Phase 6: Documentation & Deployment (Week 20-21)

### 6.1 Documentation

- **README.md**: Setup instructions, tech stack
- **ARCHITECTURE.md**: UI architecture, data flow
- **DEPLOYMENT.md**: How to deploy to Docker/K8s
- **CONFIGURATION.md**: Environment variables
- **DEVELOPMENT.md**: Local dev setup
- **API.md**: UI backend API endpoints

### 6.2 Environment Variables Configuration

```
# .env.local (development)
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_QUERY_API_URL=http://localhost:8081
NEXT_PUBLIC_ENVIRONMENT=development
NEXTAUTH_SECRET=generate-with-openssl
NEXTAUTH_URL=http://localhost:3000
KEYCLOAK_CLIENT_ID=ui-frontend
KEYCLOAK_CLIENT_SECRET=...
KEYCLOAK_ISSUER=http://localhost:8080/auth

# .env.production (in K8s secrets)
NEXT_PUBLIC_API_URL=https://api.deepSightai.com
NEXT_PUBLIC_QUERY_API_URL=https://query.deepSightai.com
NEXT_PUBLIC_ENVIRONMENT=production
NEXT_PUBLIC_SENTRY_DSN=...
NEXTAUTH_SECRET=...
```

### 6.3 Kubernetes Manifests Complete

Add:
- **Ingress** configuration (TLS via cert-manager)
- **NetworkPolicies** (pod-to-pod restrictions)
- **PodDisruptionBudget** for high availability
- **Resource quotas** and limits
- **PodSecurityContext** (non-root user)

---

## Phase 7: Advanced Features (Months 4-6)

### 7.1 Sector-Specific UI Variants

**Law Enforcement Panel**:
- Chain of custody display
- Evidence handling workflow
- CJIS compliance warnings
- License plate highlighting
- Face blur toggle

**Commercial Analytics**:
- Heatmap overlay on frames
- Demographics chart
- Queue detection dashboard
- Conversion metrics

**Logistics**:
- PPE detection compliance %
- Asset tracking timeline
- Dock door utilization heatmap

### 7.2 Mobile Responsive Design

- Tailwind responsive classes
- Touch-friendly buttons
- Simplified mobile view
- PWA support (optional)

### 7.3 Admin Panel Features

- Tenant user management (invite/suspend)
- Quota adjustment
- Billing & invoices
- Usage reports export (CSV)
- API key rotation

---

## Implementation Timeline

| Week | Task | Deliverable |
|------|------|-------------|
| 1-2 | Project setup + tech decisions | Next.js project skeleton |
| 3 | Docker + K8s config | Dockerfile, base manifests |
| 4-6 | Multi-tenant UI | Auth, tenant context, quotas |
| 7-8 | Auth integration | Login, JWT, protected routes |
| 9-12 | Core features | Upload, search, results display |
| 13-14 | Analytics dashboard | Usage charts, admin panel |
| 15-16 | CI/CD pipeline | GitHub Actions + ArgoCD |
| 17 | Observability | Prometheus metrics, Sentry |
| 18-19 | Testing | Unit + E2E tests |
| 20-21 | Docs + polish | Full documentation, optimization |
| 22-24 | Advanced features | Sector-specific, mobile, admin |

**Total**: 6 months (with 1 person)

---

## Resource Requirements

- **Frontend Engineer**: 1 (TypeScript/React/Next.js)
- **DevOps Support**: 0.5 (for K8s/CI/CD)
- **Designer**: 0.5 (optional, for custom branding)

---

## Success Criteria

- ✅ UI runs in Docker container
- ✅ Deployed to Kubernetes (k3s + cloud)
- ✅ Authentication works with existing Auth Service
- ✅ Multi-tenant data isolation in UI
- ✅ Real-time quota display and enforcement
- ✅ Audit logging of all user actions
- ✅ Health checks and metrics exposed
- ✅ CI/CD automated deployment
- ✅ Responsive design (mobile + desktop)
- ✅ Sector-specific features for LE/Commercial/Logistics
- ✅ Admin panel for tenant management
- ✅ Performance: p95 < 200ms for page loads
- ✅ Accessibility: WCAG 2.1 AA compliant

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Streamlit to React migration complex | Keep Streamlit running in parallel during migration, gradual rollout |
| Auth integration delays | Use mock auth first, integrate real JWT later |
| Performance issues | Implement code splitting, caching, CDN early |
| Multi-tenant isolation bugs | Thorough testing, RLS in backend, UI filtering |
| K8s deployment issues | Start with Docker Compose UI container, then K8s |

---

## Next Immediate Steps

1. **Create Next.js project**:
   ```bash
   npx create-next-app@latest ui-frontend --typescript --tailwind --app --no-src-dir --import-alias "@/*"
   cd ui-frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install next-auth axios react-hook-form zod @hookform/resolvers recharts lucide-react @radix-ui/react-icons shadcn-ui
   ```

3. **Set up ShadCN/ui**:
   ```bash
   npx shadcn-ui@latest init
   npx shadcn-ui@latest add button card input label badge progress dialog dropdown-menu
   ```

4. **Create basic folder structure** (src/app, src/components, src/lib)

5. **Build login page with NextAuth**

6. **Create Dockerfile and test locally**

7. **Create K8s manifests and deploy to dev cluster**

8. **Iterate with user feedback**

---

This plan transforms the current simple Streamlit UI into a production-ready, enterprise-grade, multi-tenant, cloud-native frontend that can scale to millions of users across law enforcement, commercial, and logistics sectors.
