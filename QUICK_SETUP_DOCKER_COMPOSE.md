# Quick setup of docker-compose for local development


## Set environment variables

```
cp contrib/docker/.env.template contrib/docker/.env
```

## Build the images

```
cd contrib/docker
docker-compose up -d --build
```

## Configure datastore database

```
docker exec ckan /usr/local/bin/ckan -c /etc/ckan/production.ini datastore set-permissions | docker exec -i db psql -U ckan
```

## Set up in the CKAN container

### Get inside of CKAN container

```
docker exec -it ckan /bin/bash -c "export TERM=xterm; exec bash"
```

### Install azure-auth plugin

```
source $CKAN_VENV/bin/activate && cd $CKAN_VENV/src/
pip install -e "git+https://github.com/geosolutions-it/ckanext-azure-auth.git#egg=ckanext-azure-auth"
pip install cryptography
```

### Edit production.ini

```
vim $CKAN_CONFIG/production.ini
```

set these parameters inside the [app:main] section:

```
[app:main]

ckan.plugins = < OTHER PLUGINS > datastore datapusher azure_auth
ckan.datapusher.formats = csv xls xlsx tsv application/csv application/vnd.ms-excel application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
ckan.cors.origin_allow_all = true

ckanext.azure_auth.wtrealm = api://< YOUR Azure AD APP's CLIENT ID >
ckanext.azure_auth.tenant_id = < YOUR Azure AD TENANT ID>
ckanext.azure_auth.client_id = < YOUR Azure AD APP's CLIENT ID >
ckanext.azure_auth.audience = < YOUR Azure AD APP's CLIENT ID >
ckanext.azure_auth.client_secret = < YOUR Azure AD APP's CLIENT SECRET>

# Allow plugin to create new users
ckanext.azure_auth.allow_create_users = True
# Force Multi-Factor Authentication usage
ckanext.azure_auth.force_mfa = False
# Whether to disable single sign-on and force the ADFS server to show a login prompt.
ckanext.azure_auth.disable_sso = False


ckanext.azure_auth.redirect_uri =   http://localhost:5000/azure/signin/
ckanext.azure_auth.auth_callback_path =  /azure/signin/
```

and get ouf the container.

## Restart the CKAN container

```
docker-compose restart ckan
```




