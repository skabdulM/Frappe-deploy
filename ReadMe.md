# Build Custom Image locally

### Prerequisites

Before you proceed, ensure you have the following:

- **Docker** installed on your system
- **GitLab PAT Token** with registry write access

## Steps to build custom docker image

Clone and change directory to nms_erp directory

```shell
git clone https://gitlab.com/c2k1/nms-builder.git nms_builder
cd nms_builder
```

Export your Personal Access Token (PAT)

```shell
export NMS_KEY=<YOUR_PAT_TOKEN>
export NMS_PAYROLL_KEY=<YOUR_PAT_TOKEN>
```

Export Image Name
- v16:
```shell
# for latest build
export IMAGE_NAME=registry.gitlab.com/c2k1/nms-builder/nms-erp-v16:latest

# for tagged build
export IMAGE_NAME=registry.gitlab.com/c2k1/nms-builder/nms-erp-v16:${VERSION:-$(cat ./version-16/ci/version.txt)}
```
- v15:
```shell
# for latest build
export IMAGE_NAME=registry.gitlab.com/c2k1/nms-builder/nms-erp-v15:latest

# for tagged build
export IMAGE_NAME=registry.gitlab.com/c2k1/nms-builder/nms-erp-v16:${VERSION:-$(cat ./version-15/ci/version.txt)}
```

Load `build.env`
- v16
```shell
source ./version-16/ci/build.env
```

- v15
```shell
source ./version-15/ci/build.env
```

Generate `APPS_JSON_BASE64`
- v16
```shell
# for latest build
export APPS_JSON_BASE64=$(envsubst < ./version-16/ci/apps-latest.json | base64 -w 0)

# for tagged build
export APPS_JSON_BASE64=$(envsubst < ./version-16/ci/apps.json | base64 -w 0)
```

- v15
```shell
# for latest build
export APPS_JSON_BASE64=$(envsubst < ./version-15/ci/apps-latest.json | base64 -w 0)

# for tagged build
export APPS_JSON_BASE64=$(envsubst < ./version-15/ci/apps.json | base64 -w 0)
```

Build Image
- v16
```shell
docker build \
    --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
    --build-arg=FRAPPE_BRANCH=${FRAPPE_BRANCH} \
    --build-arg=PYTHON_VERSION=${PYTHON_VERSION} \
    --build-arg=NODE_VERSION=${NODE_VERSION} \
    --build-arg=APPS_JSON_BASE64=${APPS_JSON_BASE64} \
    --tag=${IMAGE_NAME} \
    --file=./version-16/Dockerfile .
```

- v15
```shell
docker build \
    --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
    --build-arg=FRAPPE_BRANCH=${FRAPPE_BRANCH} \
    --build-arg=PYTHON_VERSION=${PYTHON_VERSION} \
    --build-arg=NODE_VERSION=${NODE_VERSION} \
    --build-arg=APPS_JSON_BASE64=${APPS_JSON_BASE64} \
    --tag=${IMAGE_NAME} \
    --file=./version-15/Dockerfile .
```

## Steps to push custom docker image

Log in to GitLab Registry

```shell
# Enter gitlab username and password when asked
docker login registry.gitlab.com
```

Push the Image to GitLab Registry

```shell
docker push ${IMAGE_NAME}
```

## Portainer multi-environment setup

See docs/portainer-multi-env.md for dev/staging/prod stacks and automated deployments.

## VPS deployment guide

See docs/vps-deployment.md for VPS prerequisites, Swarm setup, and GitHub configuration.

