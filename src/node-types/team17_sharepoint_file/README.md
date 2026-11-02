# SharePoint document library

Supports listing drive root children, retrieving item metadata, downloading UTF-8 text and uploading UTF-8 text (up to 1 MB). Binary file transfer, delete, folder creation and ETag/conflict controls are not included in this first implementation.

Replace `CREDENTIAL_TYPE` and `TOKEN_FIELD` placeholders in `node.py` with the exact Studio credential type and access-token property. The token must be valid for Graph; OAuth and refresh remain Studio responsibilities. The node only accepts site/drive IDs and builds requests against the fixed Graph host.
