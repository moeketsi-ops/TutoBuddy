#!/usr/bin/env bash
# Run in AWS CloudShell (eu-west-1). Creates IAM user katlego-worker that can
# ONLY read/delete messages on katlego-inbound.fifo, makes one access key and
# writes it straight to katlego-server:/opt/katlego/aws.env over SSH.
# The key is never printed to the screen or saved in CloudShell.
set -euo pipefail
R=eu-west-1
Q=arn:aws:sqs:eu-west-1:070780358345:katlego-inbound.fifo
IP=54.195.157.34
U=katlego-worker

aws iam get-user --user-name $U >/dev/null 2>&1 || aws iam create-user --user-name $U --tags Key=project,Value=tutobuddy >/dev/null
aws iam put-user-policy --user-name $U --policy-name katlego-sqs-consume --policy-document "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[{\"Effect\":\"Allow\",
    \"Action\":[\"sqs:ReceiveMessage\",\"sqs:DeleteMessage\",\"sqs:ChangeMessageVisibility\",\"sqs:GetQueueAttributes\"],
    \"Resource\":\"$Q\"}]}"
echo "IAM user $U ready (queue-only policy)."

N=$(aws iam list-access-keys --user-name $U --query 'length(AccessKeyMetadata)' --output text)
[ "$N" -lt 2 ] || { echo "User already has 2 keys; delete an old one first."; exit 1; }

K=$(mktemp -d); trap 'rm -rf "$K"' EXIT
aws lightsail download-default-key-pair --region $R --query privateKeyBase64 --output text > "$K/ls.pem"
chmod 600 "$K/ls.pem"
SSH="ssh -i $K/ls.pem -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ubuntu@$IP"
$SSH true || { echo "Cannot SSH to $IP from CloudShell. Nothing created beyond the IAM user."; exit 1; }

aws iam create-access-key --user-name $U --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text \
 | $SSH 'read -r id secret; sudo mkdir -p /opt/katlego; printf "AWS_ACCESS_KEY_ID=%s\nAWS_SECRET_ACCESS_KEY=%s\n" "$id" "$secret" | sudo tee /opt/katlego/aws.env >/dev/null; sudo chmod 600 /opt/katlego/aws.env; echo "Server: /opt/katlego/aws.env written ($(sudo stat -c "%s bytes, mode %a" /opt/katlego/aws.env))."'
