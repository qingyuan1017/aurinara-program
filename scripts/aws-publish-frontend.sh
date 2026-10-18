#!/usr/bin/env bash
set -euo pipefail

stack_name=${1:?usage: aws-publish-frontend.sh STACK_NAME}

output() {
  aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

export VITE_OIDC_AUTHORITY=$(output OidcAuthority)
export VITE_OIDC_CLIENT_ID=$(output SpaClientId)
export VITE_OIDC_REDIRECT_URI="$(output ApplicationUrl)/auth/callback"
export VITE_OIDC_LOGOUT_URI="$(output ApplicationUrl)/login"
export VITE_OIDC_END_SESSION_ENDPOINT=$(output OidcEndSessionUrl)
export VITE_OIDC_SCOPES="openid profile email"
export VITE_API_BASE_URL=$(output ApplicationUrl)

npm ci --prefix frontend
npm run build --prefix frontend
aws s3 sync frontend/dist "s3://$(output FrontendBucketName)" --delete --only-show-errors
aws cloudfront create-invalidation --distribution-id "$(output CloudFrontDistributionId)" --paths '/*' >/dev/null
curl --fail --retry 12 --retry-delay 10 --retry-all-errors "$(output ApplicationUrl)/health/ready"
