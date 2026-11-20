# Modo emulador: Floci en localhost + clúster kind "aegisvolt".
aws_endpoint_url         = "http://localhost:4566"
cluster_aws_endpoint_url = "http://floci:4566"

# Floci no emula APIs PRIVATE ni el plano de datos real de VPC Link: integración directa al NodePort.
api_endpoint_type = "REGIONAL"
use_vpc_link      = false

# Floci no implementa CreateVpcEndpointServiceConfiguration (PrivateLink hacia el NLB del clúster).
# En AWS real queda en true (ver aws.tfvars.example).
enable_k8s_privatelink = false

create_eks        = false
manage_kubernetes = true
kube_context      = "kind-aegisvolt"
