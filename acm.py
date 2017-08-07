from __future__ import print_function

import sys
import logging
import json
import re
import mechanize
import boto3

mechlog = logging.getLogger("mechanize")
mechlog.addHandler(logging.StreamHandler(sys.stdout))

logging.basicConfig(level=logging.DEBUG)
mechlog.setLevel(logging.DEBUG)

confirm_url = re.compile("https://.*certificates.amazon.com/approvals\?[A-Za-z0-9=&-]+")
approval_text = re.compile("You have approved")

domain_re = re.compile(".*<b>Domain name</b>.*?<td class='right-column'>\s+(.*?)\s.*", re.DOTALL)
accountid_re = re.compile(".*<b>AWS account number</b>.*?<td class='right-column'>\s+(.*?)\s.*", re.DOTALL)
region_re = re.compile(".*<b>AWS Region</b>.*?<td class='right-column'>\s+(.*?)\s.*", re.DOTALL)
certid_re = re.compile(".*<b>Certificate identifier</b>.*?<td class='right-column'>\s+(.*?)\s.*", re.DOTALL)


def panic(msg):
    raise Exception(msg)


def validate(event, context):
    logging.debug("msg %s", event['Records'][0]['Sns']['Message'])
    msg = json.loads(event['Records'][0]['Sns']['Message'])
    match = confirm_url.search(msg['content'])

    # Ignore emails that don't match the certificate confirm URL
    if not match:
        logging.error("CONFIRMATION URL DID NOT MATCH!")
        return

    url = match.group(0)
    logging.info("CONFIRMATION URL: %s", url)

    br = mechanize.Browser()
    br.set_handle_robots(False)

    # Fetch approval page
    logging.debug("OPENING CONFIRMATION URL")
    response = br.open(url)
    logging.debug("OPENED CONFIRMATION URL")
    content = response.get_data()

    # Extract confirmation page details
    domain, account_id, region, cert_id = [
        regex.match(content).group(1)
        if regex.match(content) else panic("Couldn't parse confirmation page!")
        for regex in (domain_re, accountid_re, region_re, certid_re)]

    # Remove dashes from account_id
    account_id = account_id.translate(None, '-')

    logging.info("Domain: '%s'", domain)
    logging.info("Account ID: '%s'", account_id)
    logging.info("Region: '%s'", region)
    logging.info("Certificate ID: '%s'", cert_id)

    # Check if the cert is pending validation
    acm = boto3.client('acm', region_name=region)
    cert = acm.describe_certificate(CertificateArn="arn:aws:acm:%s:%s:certificate/%s"
        % (region, account_id, cert_id))
    logging.debug(cert)

    if cert['Certificate']['Status'] != 'PENDING_VALIDATION':
        panic("Confirmation certificate is not pending validation!")

    # It's the first and only form on the page
    # Could we match on action="/approvals"?
    br.form = list(br.forms())[0]
    logging.debug("SUBMITTING CONFIRMATION FORM")
    response = br.submit()
    logging.debug("SUBMITTED CONFIRMATION FORM")
    content = response.get_data()

    match = approval_text.search(content)
    if match:
        logging.info("Certificate for %s approved!", domain)
    else:
        logging.error(content)
        panic("No confirmation of certificate approval!")
