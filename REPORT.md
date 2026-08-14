# LAB 16 — Báo cáo kết quả: Cloud AI Environment Setup (AWS)

**Sinh viên:** Trần Việt Bách — 2A202601773
**Track:** 2 — AWS / Terraform / LightGBM trên CPU
**Ngày thực hiện:** 14/08/2026

---

## 1. Môi trường triển khai

Hạ tầng được dựng hoàn toàn bằng Terraform (`terraform/`) tại region `us-east-1`:

| Thành phần | Cấu hình |
|---|---|
| VPC | `10.0.0.0/16` — 2 public subnet, 2 private subnet, 2 AZ |
| Bastion Host | `t3.micro`, public subnet, cổng vào SSH duy nhất |
| Compute Node | **`c7i-flex.large`** (2 vCPU / 4 GiB), private subnet, không có IP public |
| NAT Gateway | 1 NAT + Elastic IP, cho private subnet ra internet một chiều |
| ALB | Application Load Balancer, cổng 80 → 8000 |
| IAM | Role + Instance Profile gắn vào Compute Node |

**Ghi chú về instance type:** README chỉ định `t3.medium` (2 vCPU / 4 GB), nhưng tài khoản AWS
sử dụng đang ở **Free Plan** kiểu mới nên `RunInstances` bị từ chối với lỗi
`InvalidParameterCombination: The specified instance type is not eligible for Free Tier`.
Đã thay bằng `c7i-flex.large` — instance nằm trong danh sách free-tier-eligible và có
**đúng thông số 2 vCPU / 4 GiB** như yêu cầu, nên không ảnh hưởng tới tính so sánh của
benchmark. Các lựa chọn free-tier khác đều không phù hợp: `t3.micro` (1 GiB) sẽ OOM khi
load dataset, còn `t4g.*` là kiến trúc ARM trong khi AMI được cấu hình lọc `amd64`.

Việc thay đổi thực hiện qua biến có sẵn, không phải sửa code hạ tầng:

```bash
terraform apply -var="cpu_instance_type=c7i-flex.large"
```

---

## 2. IAM và bảo mật secret

### 2.1 Identity sử dụng

Toàn bộ lab **không dùng tài khoản Root**. Thay vào đó:

- **IAM Group `AI-Lab-Group`** — nơi gắn quyền, không gắn trực tiếp vào user
- **IAM User `ai-lab-user`** — thành viên của group, chỉ có Access Key kiểu *Command Line
  Interface*, không có quyền đăng nhập Console
- **IAM Role + Instance Profile** (`aws_iam_role.ai_role`) — gắn vào Compute Node

### 2.2 Vì sao đây là least privilege

Group được cấp đúng 4 policy, mỗi policy tương ứng một nhóm tài nguyên mà Terraform thực sự
phải tạo — thay vì cấp thẳng `AdministratorAccess` cho nhanh:

| Policy | Tài nguyên nó cho phép tạo |
|---|---|
| `AmazonEC2FullAccess` | EC2 instances, Key Pair, Security Groups |
| `AmazonVPCFullAccess` | VPC, subnets, IGW, NAT Gateway, route tables |
| `ElasticLoadBalancingFullAccess` | ALB, Target Group, Listener |
| `IAMFullAccess` | IAM Role và Instance Profile gắn vào compute node |

Nguyên tắc quan trọng thứ hai là **Instance Profile thay cho Access Key**: Compute Node được
cấp quyền thông qua Role gắn vào máy, nên không cần — và không bao giờ có — Access Key nằm
trên đĩa của instance. Nếu máy bị chiếm quyền, kẻ tấn công không lấy được credential dài hạn.

**Thừa nhận giới hạn:** các policy `*FullAccess` của AWS vẫn rộng hơn mức tối thiểu lý thuyết.
Một triển khai production nên dùng customer-managed policy giới hạn theo ARN, tag hoặc region
cụ thể. Đáng lưu ý nhất là `IAMFullAccess` — quyền này cho phép tự nâng đặc quyền
(privilege escalation), nên chỉ chấp nhận được trong môi trường lab dùng một lần và bị hủy
ngay sau khi xong. Trong thực tế nên thay bằng policy chỉ cho phép thao tác trên các role có
tiền tố tên xác định.

### 2.3 Xử lý secret

| Secret | Cách bảo vệ |
|---|---|
| AWS Access Key | Chỉ nằm trong `~/.aws/credentials` trên máy local, không bao giờ vào repo |
| SSH private key `lab-key` | Đã có trong `.gitignore`, không được commit |
| `terraform.tfstate` | Đã `.gitignore` — state chứa ID và thuộc tính tài nguyên |
| Kaggle API key | Đặt tại `~/.kaggle/kaggle.json` **trên EC2**, `chmod 600`, hủy cùng instance |
| Hugging Face token | Không dùng (chỉ cần cho phụ lục GPU) |

Private key **không bao giờ được copy lên Bastion**. Việc SSH hai chặng thực hiện bằng
ProxyJump, tức là đường hầm được mở từ máy local xuyên qua Bastion — key nằm nguyên tại chỗ:

```bash
ssh -i lab-key -J ubuntu@<BASTION_IP> ubuntu@<NODE_PRIVATE_IP>
```

---

## 3. Kiến trúc mạng và đường truy cập

```
                         Internet
                            │
              ┌─────────────┼─────────────┐
           :80│          :22│             │
    ┌─────────▼─────────────▼─────────────┴────────┐  VPC 10.0.0.0/16
    │  PUBLIC SUBNET  10.0.0.0/24, 10.0.1.0/24     │
    │   ┌──────────┐      ┌──────────────┐         │
    │   │   ALB    │      │   Bastion    │         │
    │   │   :80    │      │  t3.micro    │         │
    │   └────┬─────┘      │  public IP   │         │
    │        │            └──────┬───────┘         │
    │   ┌────▼─────┐             │ ssh :22         │
    │   │   NAT    │◄──────────┐ │                 │
    │   │ Gateway  │           │ │                 │
    │   └──────────┘           │ │                 │
    ├──────────────────────────┼─┼─────────────────┤
    │  PRIVATE SUBNET 10.0.10.0/24, 10.0.11.0/24   │
    │       :8000  ┌───────────▼─▼──────┐          │
    │   ◄──────────┤   Compute Node     │          │
    │              │  c7i-flex.large    │          │
    │              │  KHONG co IP public│          │
    │              └────────────────────┘          │
    └──────────────────────────────────────────────┘
```

**Nguyên tắc phân tầng.** Compute Node — nơi chứa dữ liệu và mô hình — nằm trong private
subnet và **không có địa chỉ IP public**. Không tồn tại đường nào từ internet đi thẳng tới
nó. Bằng chứng thực nghiệm: `ssh ubuntu@10.0.10.229` trực tiếp từ máy local trả về
`Connection refused` vì `10.0.0.0/8` là dải nội bộ, gói tin không bao giờ rời khỏi mạng LAN.

**Bastion là cổng vào duy nhất.** Chỉ một máy duy nhất mở SSH ra internet, thu bề mặt tấn
công từ N máy xuống 1. Bastion cố tình dùng `t3.micro` và không cài gì ngoài SSH — nó chỉ là
trạm trung chuyển, không lưu trữ hay xử lý gì.

**Security Group tham chiếu lẫn nhau, không dùng IP.** Đây là điểm thiết kế đáng chú ý nhất
trong `main.tf`:

```hcl
ingress {                                        # SSH: chi tu Bastion
  from_port = 22
  security_groups = [aws_security_group.bastion_sg.id]
}
ingress {                                        # HTTP: chi tu ALB
  from_port = 8000
  security_groups = [aws_security_group.alb_sg.id]
}
```

Rule trỏ vào **security group** chứ không phải dải CIDR. Khi instance được thay thế và đổi IP,
rule vẫn đúng mà không cần sửa gì — an toàn hơn và không phải bảo trì.

**NAT Gateway cho phép đi ra mà không cho đi vào.** Compute Node cần tải package pip và
dataset Kaggle (đo được 286 MB nhận vào), nhưng NAT chỉ chuyển tiếp kết nối do bên trong khởi
xướng. Không có route nào từ internet vào private subnet.

**ALB là cửa ngõ HTTP duy nhất.** Nhận cổng 80 công khai, chuyển tới cổng 8000 của Compute
Node. Ở luồng CPU mặc định không có tiến trình nào lắng nghe cổng 8000, nên health check báo
`unhealthy` — đây là trạng thái bình thường và đã được README xác nhận, không phải lỗi cấu
hình. ALB chỉ thực sự phục vụ khi làm phụ lục GPU + vLLM.

**Điểm yếu đã nhận biết.** `bastion_sg` mở cổng 22 từ `0.0.0.0/0` để bài lab chạy được ở mọi
mạng. Trong môi trường thật, nên giới hạn `cidr_blocks` về đúng IP văn phòng/VPN, hoặc bỏ hẳn
Bastion để chuyển sang AWS Systems Manager Session Manager — cách này không cần mở cổng 22 và
không cần quản lý SSH key.

---

## 4. Dataset

**Credit Card Fraud Detection** (`mlg-ulb/creditcardfraud`) — 284,807 giao dịch thực, 31 cột
(`Time`, `V1`–`V28` đã qua PCA, `Amount`, `Class`).

Đặc điểm quyết định toàn bộ cách đánh giá: dataset **cực kỳ mất cân bằng** — chỉ **492 ca
gian lận, chiếm 0.173%**. Chia stratified 80/20 thành train/test, rồi tách tiếp 20% từ train
làm validation:

```
train = 182,276 dòng (315 ca gian lận)
val   =  45,569 dòng ( 79 ca gian lận)
test  =  56,962 dòng ( 98 ca gian lận)
```

Tập validation được cắt ra **từ trong tập train**, không dùng tập test cho early stopping —
để tập test giữ nguyên vai trò đánh giá độc lập.

---

## 5. Kết quả benchmark

| Metric | Kết quả |
|---|---|
| Thời gian load data | 0.965 s |
| Thời gian training | 9.962 s |
| Best iteration | 269 |
| AUC-ROC | 0.9783 |
| Accuracy | 0.9995 |
| F1-Score | 0.8462 |
| Precision | 0.9167 |
| Recall | 0.7857 |
| Inference latency (1 row) | 0.844 ms (p95: 0.898 ms) |
| Inference throughput (1000 rows) | 178,423 rows/s (5.6 ms cho cả lô) |

**Confusion matrix trên tập test:**

|  | Dự đoán: hợp lệ | Dự đoán: gian lận |
|---|---|---|
| **Thực tế: hợp lệ** | TN = 56,857 | FP = 7 |
| **Thực tế: gian lận** | FN = 21 | TP = 77 |

Siêu tham số cuối cùng: `num_leaves=31`, `learning_rate=0.02`, `min_child_samples=20`,
`n_estimators=3000` với early stopping 200 vòng trên AUC của tập validation.

**Về tính lặp lại:** ảnh chụp `screenshots/benchmark.png` là một lần chạy khác với lần sinh ra
`benchmark_result.json`, nên các chỉ số **thời gian** lệch nhẹ (training 9.89s so với 9.96s,
throughput 167,760 so với 178,423 rows/s) — đây là dao động bình thường của phép đo trên máy
ảo dùng chung. Ngược lại, toàn bộ chỉ số **chất lượng** trùng khít tuyệt đối giữa hai lần chạy
(AUC 0.978289, F1 0.846154, best_iteration 269, confusion matrix TN=56857/FP=7/FN=21/TP=77)
nhờ cố định `random_state=42` ở cả `train_test_split` lẫn `LGBMClassifier`.

Dữ liệu thô: [`benchmark_result.json`](benchmark_result.json) — mã nguồn: [`benchmark.py`](benchmark.py)

---

## 6. Nhận xét

Trên `c7i-flex.large` (2 vCPU, 4 GiB), LightGBM huấn luyện 269 vòng trên 182,276 dòng chỉ hết
**9.96 giây**, và load 144 MB CSV hết chưa tới 1 giây. Điều này khẳng định gradient boosting ở
quy mô vài trăm nghìn dòng **không cần GPU** — chi phí và độ phức tạp của một node GPU là
không chính đáng cho lớp bài toán này. Inference đạt **0.844 ms cho 1 dòng** và **178,423
dòng/giây** khi xử lý theo lô; chênh lệch hơn 150 lần giữa hai con số cho thấy phần lớn
latency đơn lẻ là overhead cố định của lời gọi hàm chứ không phải chi phí tính toán thật, nên
gom batch là cách tối ưu hiệu quả nhất nếu triển khai thực tế.

Về chất lượng mô hình, **Accuracy 0.9995 là con số gây hiểu lầm và không nên dùng để đánh
giá**: chỉ cần đoán bừa "mọi giao dịch đều hợp lệ" đã đạt 0.9983 trên dataset lệch 0.173% này.
Hai chỉ số có ý nghĩa là **AUC-ROC 0.9783** — cho thấy mô hình phân tách hai lớp rất tốt — và
**Recall 0.7857**, nghĩa là vẫn **bỏ lọt 21 trong 98 ca gian lận** của tập test. Đối lại,
Precision 0.9167 với chỉ 7 báo động nhầm cho thấy ngưỡng mặc định 0.5 đang thiên về "chắc chắn
mới báo". Trong bài toán chống gian lận, đánh đổi này thường bị đặt sai chiều: thiệt hại từ
một giao dịch gian lận lọt lưới lớn hơn nhiều so với phiền toái của một cảnh báo nhầm, nên hạ
ngưỡng quyết định xuống dưới 0.5 để tăng Recall là hướng cải thiện đáng làm tiếp theo.

Một quan sát đáng chú ý về siêu tham số: với `learning_rate=0.05` (giá trị thử đầu tiên), mô
hình **overfit ngay từ cây thứ hai** — AUC trên validation đạt đỉnh 0.930 tại iteration 1 rồi
tụt xuống 0.805, và early stopping dừng lại với `best_iteration=1`. Nguyên nhân là tập train
chỉ có 315 mẫu dương, quá ít so với sức chứa của 31 lá mỗi cây. Giảm learning rate xuống
**0.02** buộc mô hình học chậm và đều hơn qua 269 vòng, nâng AUC từ **0.939 lên 0.978**. Bài
học rút ra: trên dữ liệu mất cân bằng cực đoan, learning rate có ảnh hưởng lớn hơn nhiều so
với độ phức tạp cây, và `best_iteration` bất thường thấp là dấu hiệu cảnh báo cần kiểm tra
đường cong validation chứ không phải kết quả để chấp nhận.

---

## 7. Tài nguyên và chi phí

**Tài nguyên quan sát trên Compute Node** (xem `screenshots/`):

- CPU: tiến trình `python3` đạt ~190% trên 2 vCPU trong giai đoạn training
- RAM: 3.7 GiB tổng, đỉnh sử dụng trong lúc load CSV; ở trạng thái nghỉ chỉ ~255 MiB
- Network: **286 MB** nhận vào qua NAT Gateway (dataset Kaggle + các gói pip)

**Chi phí ước tính (us-east-1):**

| Dịch vụ | Loại | Chi phí/giờ |
|---|---|---|
| EC2 — Compute Node | `c7i-flex.large` | xem Cost Explorer |
| EC2 — Bastion | `t3.micro` | ~$0.010 |
| NAT Gateway | 1 AZ | ~$0.045 + data transfer |
| ALB | Application | ~$0.008 |

Chi phí thực tế phát sinh: xem ảnh chụp Cost Explorer trong `screenshots/4-aws-billing.png`.

Điểm đáng lưu ý về chi phí: **NAT Gateway là khoản tốn nhất và tốn liên tục**, tính phí theo
giờ ngay cả khi Compute Node hoàn toàn nhàn rỗi — trong bài lab này nó đắt hơn cả chiếc EC2
thực sự chạy workload. Đây là lý do bước dọn dẹp không phải hình thức.

**Dọn dẹp:** toàn bộ tài nguyên đã được xóa bằng `terraform destroy` ngay sau khi thu thập
xong số liệu.

---

## 8. Phụ lục GPU + LLM

Không thực hiện. Phần này là tùy chọn và yêu cầu quota GPU (`g4dn.xlarge`), trong khi tài khoản
đang ở Free Plan vốn đã không cho phép cả `t3.medium`.
