# Cloud Platform Installation Notes

## Summary Table

| Platform | Recommended Node Type | Min Nodes | Estimated Monthly Cost (Compute + Storage) | Notes |
|----------|----------------------|-----------|--------------------------------------------|-------|
| AWS EKS | m5.large (2 vCPU, 8GB) | 3 | $300-500 | Use RDS + S3 for best HA |
| GCP GKE | n2-standard-8 (8 vCPU) | 3 | $250-450 | Use Cloud SQL + GCS |
| Azure AKS | Standard_D8s_v3 | 3 | $280-500 | Use Azure Database + Blob Storage |

---

## Platform-Specific Quick Links

- **[AWS EKS](#aws-eks-deployment)** - Full guide with EBS, RDS, ALB, S3 integration
- **[GCP GKE](#gcp-gke-deployment)** - Regional clusters, GCLB, Cloud SQL
- **[Azure AKS](#azure-aks-deployment)** - Application Gateway, Azure Database

All platforms follow the same Kubernetes manifests in `k8s/overlays/`. Only cloud-specific resources (load balancers, storage classes, IAM) differ.

---

## Universal Kubernetes Deployment

The base manifests in `k8s/base/` are vendor-neutral. Overlays customize per environment:

```bash
# For AWS, you might use k8s/overlays/aws-production/
# For GCP, k8s/overlays/gcp-production/
# For Azure, k8s/overlays/azure-production/
```

All overlays inherit from `k8s/base/` and patch with:
- Cloud-specific `StorageClass` names
- Node selectors for instance types
- LoadBalancer annotations
- IAM integration

---

## What's Next?

1. Choose your cloud platform and follow the detailed guide above
2. Complete setup and verify all pods are running
3. Configure authentication (JWT/OAuth2)
4. Set up monitoring and alerts
5. Test with a video upload

See [User Guide](user-guide/index.md) to start using deepSightAI Trinetra after deployment.
