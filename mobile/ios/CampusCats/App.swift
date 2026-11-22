import SwiftUI
import SafariServices

// Set this to the school's HTTPS origin when distributing a school-specific build.
private let schoolOrigin = ""

@main
struct CampusCatsApp: App {
    var body: some Scene { WindowGroup { ServerView() } }
}

private struct Destination: Identifiable {
    let id = UUID()
    let url: URL
}

private struct ServerView: View {
    @AppStorage("campusOrigin") private var saved = ""
    @State private var address = ""
    @State private var error = ""
    @State private var destination: Destination?
    @State private var initialized = false
    private let green = Color(red: 0.10, green: 0.24, blue: 0.20)

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("猫迹").font(.system(size: 50, weight: .bold, design: .serif)).foregroundColor(green)
            Text("连接学校的猫图鉴").font(.title2)
            TextField("学校提供的 HTTPS 地址", text: $address)
                .keyboardType(.URL).textInputAutocapitalization(.never)
                .disableAutocorrection(true).textFieldStyle(.roundedBorder)
                .onSubmit(open)
            Button("进入校园图鉴", action: open)
                .buttonStyle(.borderedProminent).tint(green)
            Text(error.isEmpty ? "首次使用请填写学校提供的地址。关闭图鉴页面可回到这里更换地址。" : error)
                .font(.footnote).foregroundColor(.secondary)
        }
        .padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.97, green: 0.97, blue: 0.94).ignoresSafeArea())
        .onAppear {
            guard !initialized else { return }
            initialized = true
            address = saved.isEmpty ? schoolOrigin : saved
            if !address.isEmpty { open() }
        }
        .fullScreenCover(item: $destination) { page in
            SafariPage(url: page.url) { destination = nil }.ignoresSafeArea()
        }
    }

    private func open() {
        let text = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parts = URLComponents(string: text),
              let host = parts.host, !host.isEmpty,
              parts.scheme?.lowercased() == "https" ||
                  (parts.scheme?.lowercased() == "http" && ["localhost", "127.0.0.1"].contains(host.lowercased())),
              parts.path.isEmpty || parts.path == "/", parts.user == nil,
              parts.password == nil, parts.fragment == nil, parts.query == nil,
              let url = parts.url else {
            error = "请输入学校提供的完整 HTTPS 服务地址。"
            return
        }
        error = ""
        saved = text
        destination = Destination(url: url)
    }
}

private struct SafariPage: UIViewControllerRepresentable {
    let url: URL
    let finish: () -> Void
    func makeCoordinator() -> Coordinator { Coordinator(finish) }
    func makeUIViewController(context: Context) -> SFSafariViewController {
        let view = SFSafariViewController(url: url)
        view.delegate = context.coordinator
        view.preferredControlTintColor = UIColor(red: 0.10, green: 0.24, blue: 0.20, alpha: 1)
        return view
    }
    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
    final class Coordinator: NSObject, SFSafariViewControllerDelegate {
        let finish: () -> Void
        init(_ finish: @escaping () -> Void) { self.finish = finish }
        func safariViewControllerDidFinish(_ controller: SFSafariViewController) { finish() }
    }
}
