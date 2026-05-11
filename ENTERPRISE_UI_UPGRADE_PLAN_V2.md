# Enterprise UI Upgrade Plan - Clear & Actionable Version

## 🎯 Quick Summary

Transform the current **Streamlit UI** → **Enterprise-grade React/Next.js app** with Docker/K8s deployment, auth, multi-tenancy, and observability.

---

## 📊 Current State vs Target State

| Aspect | Current (Streamlit) | Target (Enterprise) |
|--------|---------------------|---------------------|
| **Tech** | Streamlit (Python) | Next.js 14 + TypeScript + Tailwind |
| **Auth** | None | JWT/OAuth2 with Keycloak integration |
| **Tenancy** | Single-tenant | Multi-tenant with quotas & isolation |
| **Deployment** | Manual Python run | Docker container → Kubernetes (k3s/EKS/GKE) |
| **Config** | Hardcoded IPs | Environment variables (12-factor) |
| **Monitoring** | None | Prometheus metrics + Sentry errors |
| **CI/CD** | None | GitHub Actions → ArgoCD GitOps |
| **UI/UX** | Basic Streamlit | Responsive, sector-specific themes |
| **Observability** | None | Logs, metrics, traces, health checks |

---

## 🗺️ Implementation Phases (High-Level)

```
Phase 1: Foundation (Weeks 1-4)
├── Create Next.js project structure
├── Set up Docker containerization
├── Create K8s manifests (base overlays)
└── Implement basic UI components

Phase 2: Security & Multi-tenancy (Weeks 5-8)
├── Add authentication (NextAuth + Keycloak)
├── Build tenant context & quota system
├── Implement role-based access control
└── Add audit logging

Phase 3: Core Features (Weeks 9-12)
├── Video upload with progress & quotas
├── RTSP stream management
├── Search interface (text-based)
├── Results display with timestamps
└── Sector-specific UI variants

Phase 4: Production Readiness (Weeks 13-16)
├── CI/CD pipeline (GitHub Actions + ArgoCD)
├── Observability (Prometheus metrics)
├── Error tracking (Sentry)
├── Health checks & probes
└── Performance optimization

Phase 5: Advanced Features (Weeks 17-20)
├── Analytics dashboard (usage charts)
├── Admin panel (user/tenant management)
├── Mobile responsive design
├── PWA support (optional)
└── Advanced sector-specific features

Total: 20 weeks (~5 months) with 1 frontend engineer
```

---

## 📁 What Gets Created (File Structure)

```
ui-frontend/                          # NEW: Complete replacement for UI/
├── src/
│   ├── app/
│   │   ├── (auth)/login/page.tsx
│   │   ├── (auth)/logout/
│   │   ├── dashboard/page.tsx
│   │   ├── upload/page.tsx
│   │   ├── search/page.tsx
│   │   ├── analytics/page.tsx (admin)
│   │   ├── admin/page.tsx (super admin)
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ui/                    # ShadCN components
│   │   ├── VideoUploader.tsx
│   │   ├── SearchBox.tsx
│   │   ├── ResultsGrid.tsx
│   │   ├── QuotaMeter.tsx
│   │   ├── SectorBadge.tsx
│   │   └── RTSPManager.tsx
│   ├── contexts/
│   │   ├── TenantContext.tsx
│   │   └── AuthContext.tsx
│   ├── lib/
│   │   ├── api.ts                 # API client
│   │   ├── auth.ts                # Auth helpers
│   │   └── metrics.ts             # Prometheus metrics
│   └── types/
│       ├── api.ts
│       └── tenant.ts
├── public/
├── docker/
│   └── Dockerfile                 # Multi-stage build
├── k8s/
│   ├── base/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   ├── hpa.yaml
│   │   └── network-policy.yaml
│   └── overlays/
│       ├── development/
│       │   └── kustomization.yaml
│       └── production/
│           └── kustomization.yaml
├── .github/workflows/
│   └── ci.yml                     # Build, test, deploy
├── helm/
│   └── ui-frontend/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
├── package.json
├── next.config.js
├── tailwind.config.js
├── tsconfig.json
├── Dockerfile (root)
├── .env.example
└── README.md

# UPDATED: Existing files modified
k8s/overlays/production/           # Add UI to existing K8s setup
argocd-apps/                       # Add UI application
DEPLOYMENT.md                      # Update with UI deployment steps
```

---

## 🚀 Week-by-Week Action Plan

### **Weeks 1-2: Project Setup**

**Day 1-2: Create Next.js Project**
```bash
npx create-next-app@latest ui-frontend --typescript --tailwind --app --import-alias "@/*"
cd ui-frontend
```

**Day 3-4: Install Dependencies**
```bash
npm install next-auth axios react-hook-form zod @hookform/resolvers
npm install recharts lucide-react
npm install -D @types/node @types/react @types/react-dom
```

**Day 5-7: Set up ShadCN/ui**
```bash
npx shadcn-ui@latest init
npx shadcn-ui@latest add button card input label badge progress dialog dropdown-menu
```

**Deliverable**: Running Next.js app on `localhost:3000` with basic layout

---

### **Weeks 3-4: Docker & K8s**

**Create Dockerfile** (`ui-frontend/Dockerfile`):
```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:18-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

**Create K8s base manifests** (`k8s/base/`):
- `deployment.yaml` - 2 replicas, resource limits, probes
- `service.yaml` - ClusterIP on port 80
- `configmap.yaml` - UI-specific config
- `hpa.yaml` - Auto-scaling (min=2, max=10)

**Create overlay** (`k8s/overlays/production/kustomization.yaml`):
```yaml
bases:
- ../../base
patchesStrategicMerge:
- ./patches/ingress.yaml  # Add this
configMapGenerator:
- name: ui-frontend-config
  literals:
  - NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

**Deliverable**: UI container builds and runs locally with Docker

---

### **Weeks 5-6: Authentication**

**Add NextAuth** (`src/app/api/auth/[...nextauth]/route.ts`):
```typescript
import NextAuth from 'next-auth'
import KeycloakProvider from 'next-auth/providers/keycloak'

export default NextAuth({
  providers: [
    KeycloakProvider({
      clientId: process.env.KEYCLOAK_CLIENT_ID,
      clientSecret: process.env.KEYCLOAK_CLIENT_SECRET,
      issuer: process.env.KEYCLOAK_ISSUER,
    }),
  ],
  callbacks: {
    async session({ session, token }) {
      session.user.tenantId = token.tenantId
      session.user.roles = token.roles
      return session
    },
  },
})
```

**Create login page** (`src/app/(auth)/login/page.tsx`):
- Clean login form with Keycloak redirect
- Error handling
- Redirect back to originally requested page

**Add middleware** (`src/middleware.ts`):
```typescript
export default withAuth({
  pages: { signIn: '/auth/login' },
  callbacks: {
    authorized: ({ token, req }) => {
      // Check tenant routing, admin roles, etc.
      return !!token
    },
  },
})
```

**Deliverable**: Login/logout working, protected routes enforced

---

### **Weeks 7-8: Multi-Tenancy**

**Create TenantContext** (`src/contexts/TenantContext.tsx`):
- Load tenant info from JWT or API
- Track usage: videosUploaded, storageUsed, searchesPerformed
- Calculate `canUpload` based on quotas
- Expose `tenant` object with quotas, sector, plan

**Build QuotaMeter component**:
- Visual progress bar for upload limits
- Warning messages when接近 limits
- Color-coded: green → yellow → red

**CreateuseTenant hook** for any component to access tenant data

**Update API calls** to include tenant ID automatically

**Deliverable**: Tenant-specific UI with quota enforcement visible

---

### **Weeks 9-10: Video Upload (Core Feature)**

**Build VideoUploader component**:
- Drag & drop file upload
- Progress bar during upload
- Quota check before allowing upload
- Display remaining quota
- Error handling (file too large, wrong format)

**Create upload API route** (`src/app/api/upload/route.ts`):
- Accept video file
- Forward to Main API (`/process_video`)
- Stream progress updates (WebSocket or SSE)
- Return upload ID and status

**Integrate with existing MinIO + Main API**:
- Keep same API contract as current Streamlit UI
- Add tenant prefix if needed for multi-tenancy

**Deliverable**: Working video upload with real-time progress and quota enforcement

---

### **Weeks 11-12: Search & Results**

**Build SearchBox component**:
- Text input with search button
- Clear button
- Loading state
- Debounce (optional)

**Build ResultsGrid component**:
- 3-column responsive grid
- Each frame as card with:
  - Image (from MinIO presigned URL)
  - Timestamp (extracted from path)
  - Video ID
  - Similarity score
  - Download button

**Create search API route** (`src/app/api/search/route.ts`):
- Call Query API (port 8081 - needs to exist)
- Handle errors gracefully
- Cache results in session state

**Add timestamp parsing** (reuse existing logic from Streamlit UI)

**Deliverable**: Functional search with displayed results (requires backend query API)

---

### **Weeks 13-14: RTSP & Scene Detection**

**Build RTSPManager component**:
- Input for RTSP URL
- Validation (format, connectivity test)
- Start/Stop buttons
- Display active RTSP streams for tenant
- List of RTSP streams with status (active/inactive)

**Create RTSP API routes**:
- `/api/rtsp/start` → POST to Main API `/process_rtsp_stream`
- `/api/rtsp/stop` → (needs backend endpoint)
- `/api/rtsp/list` → List tenant's active RTSP streams

**Add Scene Detection** (optional):
- Call backend scene detection (if implemented)
- Display scene list with timestamps
- Link scenes to video playback

**Deliverable**: RTSP stream management complete

---

### **Weeks 15-16: CI/CD Pipeline**

**Create GitHub Actions workflow** (`.github/workflows/ci.yml`):
1. **Lint** - ESLint + TypeScript check
2. **Test** - Unit tests
3. **Build** - Next.js production build
4. **Docker build & push** - to GitHub Container Registry
5. **Deploy** - Update ArgoCD app (image tag)
   - `develop` branch → staging cluster
   - `main` branch → production cluster

**Configure ArgoCD**:
- Create ArgoCD Application for UI in `argocd-apps/`
- Point to `k8s/overlays/production`
- Set auto-sync with prune

**Deliverable**: Push to GitHub → auto-deploy to K8s

---

### **Weeks 17-18: Observability**

**Add Prometheus metrics** (`src/lib/metrics.ts`):
- `ui_page_views_total` - track page navigation
- `ui_api_calls_total` - all API calls with status
- `ui_search_latency_seconds` - histogram for search latency
- `ui_upload_errors_total` - error counter

**Create metrics endpoint** (`src/app/api/metrics/route.ts`):
- Expose `/api/metrics` for Prometheus scraping
- Register all metrics

**Integrate Sentry**:
- Create Sentry project
- Add DSN to K8s secrets
- Initialize in `src/lib/sentry.ts`
- Add error boundary component

**Configure logging**:
- Structured JSON logging
- Include tenant ID in all logs
- Forward to Loki (existing stack)

**Deliverable**: Metrics visible in Grafana, errors in Sentry

---

### **Weeks 19-20: Testing & Polish**

**Write unit tests**:
- Component tests with React Testing Library
- Mock API calls
- Test tenant context
- Test auth flows
- Target: 80%+ coverage

**Write E2E tests with Playwright**:
- Login/logout flow
- Upload video flow
- Search flow
- Admin features

**Performance optimization**:
- Code splitting (dynamic imports for heavy pages)
- Image optimization (Next/Image)
- Bundle analysis (`@next/bundle-analyzer`)
- Lazy loading components
- CDN for static assets (S3 + CloudFront)

**Responsive design**:
- Mobile breakpoints (sm, md, lg, xl)
- Touch-friendly buttons (min 44px)
- Simplify navigation on mobile
- Test on actual devices

**Deliverable**: Full test suite, responsive design, performance optimized

---

### **Weeks 21-22: Sector-Specific Features**

**Create SectorBadge component**:
- Display tenant sector with icon/color
- Law Enforcement: red badge with shield icon
- Commercial: blue badge with store icon
- Logistics: outline badge with truck icon

**Add SectorFilter to search page** (for LE):
- Filter by detection type: weapons, faces, license plates
- Toggles for features: "blur faces", "highlight text"

**Create AnalyticsPage** (admin only):
- Usage metrics (videos, storage, searches)
- Time-series charts (activity over time)
- Top detected objects (if detection metadata exists)
- Export CSV button

**Add AdminPage** (super admin only):
- List all tenants
- Create/edit tenants
- Adjust quotas
- Manage users (invite, suspend, delete)
- View billing (if implemented)

**Deliverable**: Sector-specific UI and admin panel

---

### **Weeks 23-24: Production Hardening**

**Add health checks**:
- `/health` endpoint (200 OK if app healthy)
- `/ready` endpoint (200 OK if DB/API reachable)
- K8s probes configured

**Add security hardening**:
- Frame options (X-Frame-Options)
- CSP headers
- HSTS
- CORS configuration (whitelist API domain)
- Regular updates (dependabot)

**Add disaster recovery**:
- Database backups (handled by backend)
- Document restore procedures
- Test backup restoration

**Add runbooks**:
- How to deploy
- How to rollback
- How to debug common issues
- Emergency contacts

**Final testing**:
- Load test with k6 or artillery
- Penetration test (internal)
- UAT with stakeholders

**Deliverable**: Production-ready, fully documented, launch-compatible

---

## ✅ Success Criteria Checklist

**Must-haves (P0)**:
- [ ] UI runs in Docker container locally
- [ ] Deployed to Kubernetes (k3s or cloud)
- [ ] Authentication with Keycloak working
- [ ] Multi-tenant isolation (user sees only their data)
- [ ] Quota display and enforcement
- [ ] Video upload with progress bar
- [ ] Search with results display
- [ ] RTSP stream management
- [ ] CI/CD automated (push → deploy)
- [ ] Health checks and metrics
- [ ] Error tracking (Sentry)

**Should-haves (P1)**:
- [ ] Mobile responsive design
- [ ] Analytics dashboard
- [ ] Admin panel for tenant management
- [ ] Sector-specific UI variants
- [ ] Performance: p95 < 200ms page load
- [ ] Unit + E2E test coverage > 80%
- [ ] Documentation complete

**Nice-to-haves (P2)**:
- [ ] PWA support
- [ ] Advanced search filters
- [ ] Real-time collaboration (shared workspaces)
- [ ] Annotation tools
- [ ] Export reports (PDF)

---

## 🎯 Immediate Next Steps (This Week)

1. **Set up Next.js project** (Day 1)
   ```bash
   npx create-next-app@latest ui-frontend --typescript --tailwind --app --import-alias "@/*"
   ```

2. **Review tech stack** with team:
   - Are you comfortable with TypeScript/React?
   - Or should we keep Streamlit? (See "Alternative Path" below)

3. **Get access to Keycloak**:
   - Need client ID/secret for UI
   - Need issuer URL
   - Test login flow manually

4. **Spin up dev K8s cluster** (if not already):
   ```bash
   # k3d (k3s in Docker) - easiest
   k3d cluster create dev --agents 2
   
   # Or minikube
   minikube start --memory=8192 --cpus=4
   ```

5. **Install ArgoCD** on dev cluster:
   ```bash
   kubectl create namespace argocd
   kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   ```

6. **Create first ArgoCD app** for UI (will fail until we have manifests, but set up now)

---

## 🔄 Alternative Path: Keep Streamlit

If you want to **avoid full rewrite**, here's the simpler path:

### Streamlit Enterprise Upgrade (8 weeks)

1. **Week 1-2**: Dockerize current Streamlit UI
   - Create Dockerfile
   - Multi-stage build
   - Test locally

2. **Week 3-4**: Add auth via custom component
   - Use `streamlit-authenticator`
   - Integrate with Keycloak OIDC
   - Tenant selection after login

3. **Week 5-6**: Add quota display
   - Fetch tenant quotas from API
   - Show upload limits
   - Block upload when limit reached

4. **Week 7-8**: Deploy to K8s + monitoring
   - Create K8s manifests
   - Add health checks
   - Configure ingress
   - Set up basic monitoring

**Result**: Enterprise-ready but still Streamlit (limited customization)

**Trade-offs**:
- ✅ Faster (8 weeks vs 24 weeks)
- ✅ Less JavaScript/TypeScript work
- ❌ Limited UI customization
- ❌ Poor mobile experience
- ❌ Harder to add complex features later
- ❌ Streamlit-specific limitations

---

## 📋 Decision Matrix

| Factor | Next.js Rewrite | Streamlit Upgrade |
|--------|----------------|-------------------|
| **Time** | 6 months | 2 months |
| **Cost** | High (1 FTE × 6 mo) | Low (0.25 FTE × 2 mo) |
| **Customization** | Unlimited | Limited |
| **Performance** | Excellent | Good |
| **Mobile** | Fully responsive | Poor |
| **Auth Integration** | Native JWT | Workarounds |
| **Future Features** | Easy to add | Hard to add |
| **Team Skills** | Needs React expert | Python-only |
| **Long-term** | Scalable | Limited |

**Recommendation**: Next.js if this is a core revenue product. Streamlit if UI is internal/admin-only.

---

## ❓ Questions to Answer Before Starting

1. **Who will build this?**
   - Do you have React/TypeScript expertise in-house?
   - Or need to hire/contract?

2. **Timeline urgency?**
   - Need it in 2 months → Streamlit upgrade
   - Can wait 6 months → Next.js rewrite

3. **Budget?**
   - 1 Frontend engineer × 6 months = ~$120-180k (US rates)
   - Plus DevOps/design support

4. **User base?**
   - Internal/admin users (10s) → Streamlit OK
   - External customers (100s-1000s) → Next.js needed

5. **Mobile required?**
   - Yes → Next.js
   - Desktop only → Streamlit works

---

## 📞 Support & Questions

**After implementing**:
- Review DEPLOYMENT.md for K8s deployment steps
- Check existing `k8s/` and `argocd-apps/` directories for patterns
- Use same Docker registry as other services
- Follow same Helm/Kustomize conventions

**Key touchpoints with existing code**:
- Auth Service (port 8080) for JWT
- Main API (port 8080) for upload/RTSP
- Query API (port 8081) for search - needs to exist
- K8s cluster already set up? (Check k8s/ and kubernetes/ dirs)
- ArgoCD already installed? (Check argocd-apps/)

---

**Plan Version**: 2.0 (Clear & Actionable)
**Created**: April 4, 2026
**Status**: Ready for Review & Approval
